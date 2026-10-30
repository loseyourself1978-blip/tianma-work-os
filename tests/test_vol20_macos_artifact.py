"""Actual frozen artifact validation. Set TWOS_TEST_MACOS_APP to the built app.

All accounts, workspaces and receipts are disposable engineering fixtures, not
Owner acceptance. No provider authentication, orders or external model calls.
"""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import plistlib
import secrets
import select
import socket
import subprocess
import sys
import time

import httpx
import pytest

APP = os.environ.get("TWOS_TEST_MACOS_APP")
pytestmark = pytest.mark.skipif(not APP, reason="Build the macOS artifact and set TWOS_TEST_MACOS_APP for the separate installer gate")


def executable():
    return Path(APP) / "Contents/Resources/engine/twos-service"


@contextmanager
def service(root):
    child = subprocess.Popen([str(executable()), "--diagnostic-root", str(root)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        deadline = time.monotonic() + 90
        ready = None
        while time.monotonic() < deadline:
            if select.select([child.stdout], [], [], .1)[0]:
                line = child.stdout.readline()
                assert line, "Bundled service exited before readiness"
                item = json.loads(line)
                assert item["event"] != "error", item.get("code")
                if item["event"] == "ready":
                    ready = item
                    break
        assert ready, "Bundled service startup timeout"
        yield child, ready
    finally:
        child.stdin.close()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.wait(timeout=15)
        assert child.returncode == 0, "Owned bundled service did not shut down cleanly"


def post(client, path, payload):
    response = client.post(path, json=payload)
    assert response.status_code in (200, 201), (path, response.status_code)
    return response.json()


def test_app_identity_and_bundled_native_dependencies():
    info = plistlib.loads((Path(APP) / "Contents/Info.plist").read_bytes())
    assert info["CFBundleDisplayName"] == "Tianma Work OS"
    assert info["CFBundleShortVersionString"] == "1.0.3"
    assert info["CFBundleIdentifier"] == "com.tianma.workos"
    assert len(info["TWOSSourceInputSHA256"]) == 64
    subprocess.run(["codesign", "--verify", "--deep", "--strict", APP], check=True, capture_output=True)
    result = subprocess.check_output([str(executable()), "--twos-sidecar", "--help"], text=True)
    assert "--ticket" in result
    assert not list(Path(APP).rglob("auth.json"))
    assert not list(Path(APP).rglob("*.sqlite3"))
    assert not list(Path(APP).rglob("node_modules"))


def test_frozen_native_recovery_protocol_cancel_reset_and_restart(tmp_path):
    """Packaged pipe/backend gate; separate from personal native OS-auth UI."""
    import sqlite3
    root=tmp_path.resolve()/'recovery-desktop'
    old=secrets.token_urlsafe(24);new=secrets.token_urlsafe(24)
    with service(root) as (_,ready):
        base=ready['url'].removesuffix('/projects').removesuffix('/twos')
        with httpx.Client(base_url=base,trust_env=False,headers={'Origin':base},timeout=30) as client:
            post(client,'/api/setup/start',{'confirmation':'START_FIRST_RUN'})
            post(client,'/api/setup/start',{'confirmation':'CONFIRM_INSTALLATION'})
            post(client,'/api/setup/owner',dict(username='packaged-recovery-fixture',password=old,
                 password_confirmation=old,setup_authorization=ready['setup'],request_id='native-recovery-fixture'))
            post(client,'/api/setup/managed-workspace',{'confirmed':True})
            post(client,'/api/setup/optional-tools',{'decision':'skip'})
            post(client,'/api/setup/finish',{'confirmation':'FINISH_FIRST_RUN'})
            project=post(client,'/api/projects',{'key':'RECOVERY','name':'Preserved recovery project'})
            cookies=dict(client.cookies)
    db=root/'data/twos.sqlite3'
    def business():
        with sqlite3.connect(db) as connection:
            return {name:connection.execute('SELECT * FROM "'+name+'"').fetchall() for (name,) in
                    connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('users','session_tokens','audit_events','sqlite_sequence')").fetchall()}
    before=business()
    for confirm in (False,True):
        child=subprocess.Popen([str(executable()),'--twos-owner-recovery','--diagnostic-root',str(root)],
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            assert select.select([child.stdout],[],[],20)[0], 'No packaged recovery preview'
            preview=json.loads(child.stdout.readline());assert preview['event']=='recovery_preview'
            if confirm:
                payload={k:preview[k] for k in ('nonce','installation_id','owner_id')}
                payload.update(confirmation='RESET_EXISTING_OWNER_PASSWORD',password=new,password_confirmation=new)
                stdout,stderr=child.communicate(json.dumps(payload)+'\n',timeout=30)
                assert child.returncode==0 and json.loads(stdout)['event']=='recovery_complete'
            else:
                stdout,stderr=child.communicate('',timeout=30)
                assert child.returncode==1 and json.loads(stdout)['code']=='RECOVERY_CANCELLED'
            assert old not in stdout+stderr and new not in stdout+stderr
            assert business()==before
        finally:
            if child.poll() is None:child.terminate();child.wait(timeout=10)
    with service(root) as (_,ready):
        base=ready['url'].removesuffix('/projects').removesuffix('/twos')
        with httpx.Client(base_url=base,trust_env=False,headers={'Origin':base},timeout=30,cookies=cookies) as client:
            assert client.get('/api/auth/session').json()['authenticated'] is False
            assert client.post('/api/auth/login',json={'username':'packaged-recovery-fixture','password':old}).status_code==401
            post(client,'/api/auth/login',{'username':'packaged-recovery-fixture','password':new})
            saved=client.get('/api/projects')
            assert saved.status_code==200
            assert any(p['id']==project['id'] and p['name']=='Preserved recovery project' for p in saved.json())


def test_frozen_first_run_project_task_contract_and_restart(tmp_path):
    root = tmp_path / "desktop"
    password = secrets.token_urlsafe(24)
    with service(root) as (child, ready):
        base = ready["url"].removesuffix("/projects").removesuffix("/twos")
        with httpx.Client(base_url=base, trust_env=False, headers={"Origin": base}, timeout=30) as client:
            assert client.get("/api/health").json()["version"] == "1.0.3"
            assert client.get("/api/setup/status").json()["owner_exists"] is False
            post(client, "/api/setup/start", {"confirmation": "START_FIRST_RUN"})
            post(client, "/api/setup/start", {"confirmation": "CONFIRM_INSTALLATION"})
            post(client, "/api/setup/owner", dict(username="installer-fixture", password=password,
                 password_confirmation=password, setup_authorization=ready["setup"], request_id="desktop-artifact-fixture-001"))
            post(client, "/api/setup/managed-workspace", {"confirmed": True})
            post(client, "/api/setup/optional-tools", {"decision": "skip"})
            post(client, "/api/setup/finish", {"confirmation": "FINISH_FIRST_RUN"})
            project = post(client, "/api/projects", {"key": "DESKTOP_TEST", "name": "Installer persisted project"})
            workspace = post(client, f"/api/projects/{project['id']}/managed-workspace", {"confirmed": True})
            task = post(client, "/api/tasks", {"project_id": project["id"], "title": "Installer persistence", "workflow_type": "general", "development_task": "Create the exact fixture result without other changes."})
            contract = post(client, f"/api/tasks/{task['id']}/artifact-verification", {"path": "result.txt", "expected_text": "INSTALLER VERIFIED\n"})
            # Execute the shipped verifier on an isolated Git worktree, not a host
            # Python helper. This is a deterministic fixture, not an AI delivery.
            source = Path(workspace["workspace"])
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
            work = tmp_path / "verification-worktree"
            subprocess.run(["git", "worktree", "add", "--detach", str(work), commit], cwd=source, check=True, capture_output=True)
            (work / "result.txt").write_text("INSTALLER VERIFIED\n")
            payload = {"specification": {"schema": "twos.exact_artifact.v1", "path": "result.txt", "expected_text": "INSTALLER VERIFIED\n"}, "source": str(source), "commit": commit}
            encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
            verification = subprocess.run([str(executable()), "--twos-verify", "--contract", encoded], cwd=work, capture_output=True, text=True, check=True)
            events = [json.loads(line) for line in verification.stdout.splitlines()]
            result = json.loads(next(event["item"]["text"] for event in events if event["type"] == "item.completed"))
            # The immutable v1.0.0 raw JSONL contract and its parser require
            # lowercase pass/fail; the API presentation envelope uses uppercase.
            assert result == {"schema": "twos.verification.v1", "verdict": "pass",
                              "changed_files_checked": ["result.txt"], "unexpected_files": [],
                              "exact_content": "pass", "tests": "not_applicable",
                              "git_boundary": "pass", "remote_boundary": "pass"}
            (work / "result.txt").write_text("incorrect fixture output\n")
            rejected = subprocess.run([str(executable()), "--twos-verify", "--contract", encoded], cwd=work,
                                      capture_output=True, text=True, check=True)
            rejected_events = [json.loads(line) for line in rejected.stdout.splitlines()]
            rejected_result = json.loads(next(event["item"]["text"] for event in rejected_events if event["type"] == "item.completed"))
            assert rejected_result["verdict"] == "fail"
            assert rejected_result["exact_content"] == "fail"
            (work / "result.txt").write_text("INSTALLER VERIFIED\n")
            (root / "verification-fixture-receipt.json").write_text(json.dumps(result))
            task_id, project_id = task["id"], project["id"]
    with service(root) as (child, ready):
        assert ready["setup"] == ""
        base = ready["url"].removesuffix("/projects").removesuffix("/twos")
        with httpx.Client(base_url=base, trust_env=False, headers={"Origin": base}, timeout=30) as client:
            post(client, "/api/auth/login", {"username": "installer-fixture", "password": password})
            assert client.get("/api/setup/status").json()["state"] == "ready"
            assert any(row["id"] == task_id for row in client.get("/api/tasks").json())
            assert any(row["id"] == project_id for row in client.get("/api/projects").json())
            assert client.get(f"/api/projects/{project_id}/workspace").json()["authorized"]
            assert client.get(f"/api/tasks/{task_id}/artifact-verification").json()["contract"] == contract["contract"]
            assert client.get("/api/health").json()["database"] == "ok"


def test_frozen_detached_sidecar_executes_and_persists_receipt(tmp_path, monkeypatch):
    from tests.test_vol18_codex_exec_bridge import _prepare, _wait_for_terminal
    from twos_runtime.codex_exec_bridge import launch_sidecar, load_final_message
    script = '''import json, pathlib, sys
sys.stdin.buffer.read()
pathlib.Path(sys.argv[1]).write_text("Frozen sidecar verified")
for event in [
 {"type":"thread.started","thread_id":"fixture"},
 {"type":"turn.started","turn_id":"fixture"},
 {"type":"item.completed","item":{"type":"agent_message","text":"Frozen sidecar verified"}},
 {"type":"turn.completed","turn_id":"fixture"}]:
 print(json.dumps(event), flush=True)
'''
    handle, _, _ = _prepare(tmp_path, script, timeout_seconds=20)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    launch_sidecar(handle, python_executable=str(executable()))
    receipt = _wait_for_terminal(handle, timeout=30)
    assert receipt["terminal_state"] == "COMPLETED"


@pytest.mark.parametrize("fault,code", [("permissions", "DESKTOP_STORAGE_UNAVAILABLE"), ("configuration", "DESKTOP_INSTALLATION_MISMATCH"), ("port", "DESKTOP_PORT_OCCUPIED")])
def test_frozen_failures_return_only_stable_nonsecret_codes(tmp_path, fault, code):
    root = tmp_path / "desktop"
    with service(root) as (_, ready):
        port = int(ready["url"].split(":")[2].split("/")[0])
    reservation = None
    if fault == "permissions":
        (root / "data").chmod(0o755)
    elif fault == "configuration":
        path = root / "data/installation.json"
        value = json.loads(path.read_text())
        value["source_version"] = "incompatible-fixture"
        path.write_text(json.dumps(value))
    else:
        reservation = socket.socket()
        reservation.bind(("127.0.0.1", port))
        reservation.listen()
    try:
        result = subprocess.run([str(executable()), "--diagnostic-root", str(root)], input="", capture_output=True, text=True, timeout=30)
        assert result.returncode == 1
        records = [json.loads(line) for line in result.stdout.splitlines()]
        assert records[-1] == {"event": "error", "code": code}
        assert "Traceback" not in result.stdout
        assert "setup=" not in result.stdout
    finally:
        if reservation:
            reservation.close()
