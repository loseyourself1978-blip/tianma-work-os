from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest
from sqlalchemy import select

from tests.test_vol19_owner_commit_push_delivery import (
    _canonical_applied_delivery, _create_proposal, _approve_proposal, _confirm_commit, _git,
)
import tests.test_vol19_owner_commit_push_delivery as delivery_fixture
from tests.test_vol19_guided_acceptance_corrections import commit_ui, function, node
from twos_runtime import repository_identity as identity
from twos_runtime.models import AuditEvent, ApplySession, PostApplyVerification


@pytest.fixture(autouse=True)
def private_environment(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)
    home = tmp_path / "private-home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("HOME", str(home))
    (home / ".gitconfig").write_text("[user]\n name = Synthetic Global\n email = global@example.invalid\n")


def url(f):
    return f"/api/post-apply-verifications/{f.verification['id']}/git-identity"


def setup(f, name="Synthetic Owner", email="owner@example.invalid", **extra):
    response = f.client.get(url(f), headers=f.headers)
    assert response.status_code == 200, response.text
    config = response.json()
    return f.client.post(url(f), headers=f.headers, json={
        "confirmation": "SAVE_REPOSITORY_GIT_IDENTITY", "name": name, "email": email,
        "expected_config_digest": config["config_digest"],
        "expected_repository_identity": config["repository_identity"], **extra})


def fingerprint(f):
    files = {str(p.relative_to(f.source_repo)): hashlib.sha256(p.read_bytes()).hexdigest()
             for p in f.source_repo.rglob("*") if p.is_file() and ".git" not in p.parts}
    return {"head": _git(f.source_repo, "rev-parse", "HEAD"),
            "index": (f.source_repo / ".git/index").read_bytes(), "files": files,
            "global": (Path.home() / ".gitconfig").read_bytes(),
            "remotes": _git(f.source_repo, "remote", "-v")}


@pytest.mark.parametrize("missing", ["both", "email", "neither"])
def test_owner_save_identity_preserves_delivery_and_enables_review(tmp_path, monkeypatch, missing):
    original = delivery_fixture.make_client
    def missing_local(*args, **kwargs):
        repo = args[1]
        for key in (["user.name", "user.email"] if missing == "both" else ["user.email"] if missing == "email" else []):
            _git(repo, "config", "--local", "--unset-all", key)
        return original(*args, **kwargs)
    monkeypatch.setattr(delivery_fixture, "make_client", missing_local)
    with _canonical_applied_delivery(tmp_path / "delivery") as f:
        before = fingerprint(f)
        initial = f.client.get(url(f), headers=f.headers).json()
        assert initial["repository"] == str(f.source_repo)
        assert initial["task_id"] == f.task_id
        assert "global@example.invalid" not in json.dumps(initial)
        if missing != "neither":
            assert initial["fields"]["user.email"] == "inherited_only"
        response = setup(f)
        assert response.status_code == 200, response.text
        assert response.json()["review"]["author_readiness"]["ready"]
        assert fingerprint(f) == before
        proposal = _create_proposal(f)
        assert proposal.status_code == 200, proposal.text
        assert proposal.json()["proposal"]["status"] == "READY", proposal.text
        assert proposal.json()["proposal"]["approval"] is None
        with f.factory() as session:
            applied = session.scalar(select(ApplySession))
            verified = session.scalar(select(PostApplyVerification))
            assert applied.state == "APPLIED" and verified.status == "PASSED"
            assert verified.verification_digest == f.verification["advanced"]["verification_digest"]
        again = setup(f)
        assert again.status_code == 200 and again.json()["changed"] is False
        assert again.json()["review"]["review_required"] is False
        assert fingerprint(f) == before
        # This real Commit is confined to a synthetic isolated test repository.
        p = proposal.json()["proposal"]
        approval = _approve_proposal(f, p).json()["proposal"]["approval"]
        committed = _confirm_commit(f, p, approval)
        assert committed.status_code == 200, committed.text
        assert _git(f.source_repo, "show", "-s", "--format=%an <%ae>", "HEAD") == "Synthetic Owner <owner@example.invalid>"


def test_identity_change_permanently_invalidates_proposal_and_approval(tmp_path):
    with _canonical_applied_delivery(tmp_path / "delivery") as f:
        proposal = _create_proposal(f).json()["proposal"]
        approval = _approve_proposal(f, proposal).json()["proposal"]["approval"]
        before = fingerprint(f)
        assert setup(f).status_code == 200
        assert setup(f, "TWOS Test", "twos-test@example.invalid").status_code == 200
        assert _approve_proposal(f, proposal).status_code == 409
        assert _confirm_commit(f, proposal, approval).status_code == 409
        review = f.client.get(url(f).replace("git-identity", "commit-proposals"), headers=f.headers).json()
        assert review["review_required"] and not review["proposal"]["actions"]["can_commit"]
        assert review["proposal"]["status"] == "INVALIDATED"
        assert review["proposal"]["approval"]["state"] == "INVALIDATED"
        assert review["proposal"]["approval"]["historical_state"] == "APPROVED"
        replacement = _create_proposal(f).json()["proposal"]
        assert replacement["id"] != proposal["id"] and replacement["approval"] is None
        assert replacement["status"] == "READY"
        assert fingerprint(f) == before


def test_lock_partial_failure_and_stale_save_do_not_publish_or_remove_foreign_lock(tmp_path, monkeypatch):
    with _canonical_applied_delivery(tmp_path / "delivery") as f:
        before = fingerprint(f)
        config = f.source_repo / ".git/config"
        original = config.read_bytes()
        lock = f.source_repo / ".git/config.lock"
        lock.write_text("another process owns this")
        response = setup(f)
        assert response.status_code == 409 and "GIT_CONFIG_LOCKED" in response.text
        assert lock.read_text() == "another process owns this" and config.read_bytes() == original
        lock.unlink()  # Test fixture owns this lock; product must never delete it.
        git = identity._git
        def fail_second(root, *args):
            if "--replace-all" in args and "user.email" in args:
                raise OSError("synthetic disk failure")
            return git(root, *args)
        with monkeypatch.context() as patch:
            patch.setattr(identity, "_git", fail_second)
            response = setup(f)
        assert response.status_code == 409 and "GIT_CONFIG_WRITE_FAILED" in response.text
        assert config.read_bytes() == original and not lock.exists()
        assert setup(f, expected_config_digest="0" * 64).status_code == 409
        assert setup(f, expected_repository_identity="0" * 64).status_code == 409
        assert config.read_bytes() == original and fingerprint(f) == before


def test_other_config_changes_are_not_blessed_by_identity_setup(tmp_path):
    with _canonical_applied_delivery(tmp_path / "delivery") as f:
        _git(f.source_repo, "config", "core.fileMode", "false")
        saved = setup(f)
        assert saved.status_code == 200
        assert saved.json()["review"]["actions"]["can_review_commit"] is False
        proposal = _create_proposal(f).json()["proposal"]
        assert proposal["status"] == "EXPIRED"
        assert any(row["code"] == "CONFIG_CHANGED" for row in proposal["blockers"])


def test_access_csrf_symlink_and_restart(tmp_path):
    from fastapi.testclient import TestClient
    from twos_runtime.app import create_app
    from tests.test_self_hosting import OWNER_PASSWORD
    with _canonical_applied_delivery(tmp_path / "delivery") as f:
        before = fingerprint(f)
        config = f.client.get(url(f)).json()
        body = {"confirmation": "SAVE_REPOSITORY_GIT_IDENTITY", "name": "Synthetic Owner",
                "email": "owner@example.invalid", "expected_config_digest": config["config_digest"],
                "expected_repository_identity": config["repository_identity"]}
        for headers in ({"Origin": "https://foreign.invalid"}, {"Sec-Fetch-Site": "cross-site"},
                        {"Origin": "http://testserver:9999"}):
            assert f.client.post(url(f), headers=headers, json=body).status_code == 403
        assert f.client.post(url(f), json={**body, "path": "/foreign"}).status_code == 422
        assert f.client.post(url(f).replace(f.verification["id"], "foreign"), json=body).status_code == 404
        config_path = f.source_repo / ".git/config"
        original = config_path.read_bytes()
        held = config_path.with_name("fixture-config")
        config_path.rename(held)
        config_path.symlink_to(held)
        try:
            assert f.client.post(url(f), json=body).status_code == 409
            assert held.read_bytes() == original
        finally:
            config_path.unlink()
            held.rename(config_path)
        assert f.client.post("/api/auth/logout").status_code == 200
        assert f.client.post(url(f), json=body).status_code == 401
        # The product has one initial Owner; use an isolated foreign principal
        # fixture to exercise authorization, not a nonexistent second-signup flow.
        from datetime import timedelta
        from twos_runtime.models import User, SessionToken, utc_now
        from twos_runtime.security import hash_password, hash_token
        password_hash, salt = hash_password(OWNER_PASSWORD)
        token = "synthetic-foreign-identity-test-session"
        with f.factory() as session:
            foreign = User(username="foreign-owner", password_hash=password_hash, password_salt=salt, is_active=True)
            session.add(foreign); session.flush()
            session.add(SessionToken(user_id=foreign.id, token_hash=hash_token(token), expires_at=utc_now() + timedelta(hours=1)))
            session.commit()
        foreign_headers = {"Authorization": "Bearer " + token}
        assert f.client.get(url(f), headers=foreign_headers).status_code == 404
        assert f.client.post(url(f), headers=foreign_headers, json=body).status_code == 404
        assert f.client.post("/api/auth/login", json={"username": "owner", "password": OWNER_PASSWORD}).status_code == 200
        response = setup(f)
        assert response.status_code == 200, response.text
        settings, endpoint = f.client.app.state.settings, url(f)
        assert fingerprint(f) == before
    # Stop old app lifespan, restart new app against the same isolated database.
    with TestClient(create_app(settings, start_scheduler=False)) as restarted:
        assert restarted.post("/api/auth/login", json={"username": "owner", "password": OWNER_PASSWORD}).status_code == 200
        current = restarted.get(endpoint).json()
        assert current["fields"] == {"user.name": "repository_local", "user.email": "repository_local"}
        review = restarted.get(endpoint.replace("git-identity", "commit-proposals")).json()
        assert review["author_readiness"]["ready"]
        assert review["actions"]["can_review_commit"]


def test_write_failure_after_intent_revokes_old_review_without_partial_config(tmp_path, monkeypatch):
    with _canonical_applied_delivery(tmp_path / "delivery") as f:
        p = _create_proposal(f).json()["proposal"]
        original = (f.source_repo / ".git/config").read_bytes()
        before = fingerprint(f)
        replace = os.replace
        def fail_publish(src, dst, **kwargs):
            if str(src) == "config.lock":
                raise OSError("synthetic publication failure")
            return replace(src, dst, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(identity.os, "replace", fail_publish)
            result = setup(f)
        assert result.status_code == 409
        assert (f.source_repo / ".git/config").read_bytes() == original
        assert fingerprint(f) == before
        assert not (f.source_repo / ".git/config.lock").exists()
        assert _approve_proposal(f, p).status_code == 409
        assert setup(f, "Second Synthetic", "retry@example.invalid").status_code == 200
        assert _create_proposal(f).json()["proposal"]["status"] == "READY"


def test_configuration_source_without_global_or_with_local_override(tmp_path):
    from tests.test_self_hosting import make_source_repo
    repo = make_source_repo(tmp_path)
    assert set(identity.configuration_state(repo)["fields"].values()) == {"repository_local"}
    _git(repo, "config", "--unset-all", "user.name")
    assert identity.configuration_state(repo)["fields"]["user.name"] == "inherited_only"
    (Path.home() / ".gitconfig").unlink()
    assert identity.configuration_state(repo)["fields"]["user.name"] == "missing"


def test_fresh_install_scopes_save_to_the_authorized_project(tmp_path):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from twos_runtime.app import create_app
    from tests import test_vol20_ga_remediation as ga
    from tests.test_self_hosting import make_source_repo, approve_pack, start_codex_run, wait_for_run
    settings, first = ga.installed(tmp_path)
    other = tmp_path / "other-project"
    other.mkdir()
    second = make_source_repo(other)
    _git(second, "config", "--unset-all", "user.name")
    _git(second, "config", "--unset-all", "user.email")
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        ga.setup(client, settings, first)
        project = ga.new_project(client)
        task = ga.new_task(client, project)
        assert ga.authorize(client, project, second).status_code == 200
        ga.config(client, project)
        ga.contract(client, task)
        pack = ga.prepare(client, task)
        approve_pack(client, {}, task, pack["id"])
        run = start_codex_run(client, {}, task, pack).json()["id"]
        assert wait_for_run(client, {}, run, {"completed", "failed"}, timeout=60)["status"] == "completed"
        ga.apply_result(client, run)
        guide = client.get(f"/api/tasks/{task}/first-delivery").json()
        assert guide["next_action"] == "commit_identity"
        verification = guide["delivery"]["post_apply_verification"]["verification"]
        f = SimpleNamespace(client=client, headers={}, verification=verification)
        original_first = (first / ".git/config").read_bytes()
        form = client.get(url(f)).json()
        assert form["project_id"] == project and form["repository"] == str(second)
        original_second = (second / ".git/config").read_bytes()
        held = second.with_name("held-repository")
        second.rename(held)
        second.symlink_to(held, target_is_directory=True)
        try:
            blocked = client.get(url(f))
            assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "PATH_SYMLINK_UNSAFE"
            response = client.post(url(f), json={"confirmation": "SAVE_REPOSITORY_GIT_IDENTITY",
                "name": "Fixture", "email": "fixture@example.invalid",
                "expected_config_digest": form["config_digest"],
                "expected_repository_identity": form["repository_identity"]})
            assert response.status_code == 409 and response.json()["error"]["code"] == "PATH_SYMLINK_UNSAFE"
            assert (held / ".git/config").read_bytes() == original_second
        finally:
            second.unlink()
            held.rename(second)
        saved = setup(f)
        assert saved.status_code == 200, saved.text
        assert saved.json()["review"]["actions"]["can_review_commit"]
        assert (first / ".git/config").read_bytes() == original_first
        assert _git(second, "config", "--local", "user.name") == "Synthetic Owner"


@pytest.mark.parametrize("name,email", [
    ("", "owner@example.invalid"), (" leading", "owner@example.invalid"),
    ("Name\nInjected", "owner@example.invalid"), ("Name", "bad"),
    ("Name", "@example.invalid"), ("Name", "x@"), ("Name", "x@y z"),
    ("Name <Other>", "x@y"), ("Name", "x@y\x00"), ("名" * 180, "x@y"), ("\ud800", "x@y"),
])
def test_invalid_identity_is_rejected_before_mutation(name, email):
    from twos_runtime.commit_builder import CommitBuilderError
    with pytest.raises(CommitBuilderError):
        identity.validate_identity(name, email)


def test_ui_empty_explicit_fields_and_readiness_refresh():
    html = Path("static_cockpit/vol12_static_mvp/twos_command_center.html").read_text()
    assert 'id="commit-identity-name"' in html and 'id="commit-identity-email"' in html
    assert "not your login password" in html
    open_code = function("openCommitIdentity")
    assert 'byId("commit-identity-name").value = ""' in open_code
    assert 'byId("commit-identity-email").value = ""' in open_code
    save = function("saveCommitIdentity")
    assert 'confirmation: "SAVE_REPOSITORY_GIT_IDENTITY"' in save
    assert 'assertOwnerDeliveryActionCurrent(saved.context)' in save
    assert 'await refreshWorkspace({ force: true })' in function("performAction")
    output = commit_ui({"run_id": 1, "delivery_contract": "VOL19_19_1D",
        "apply_session": {"session": {"state": "APPLIED"}},
        "post_apply_verification": {"verification": {"id": "verify", "status": "PASSED"}},
        "commit_delivery": {"author_readiness": {"status": "NEEDS_SETUP", "ready": False},
                            "actions": {"can_review_commit": False}}})
    assert output["elements"]["configureCommitIdentity"]["hidden"] is False
    assert output["elements"]["reviewOwnerCommit"]["disabled"] is True


@pytest.mark.parametrize("failure", [False, True])
def test_identity_save_refreshes_authority_even_after_failure(failure):
    harness = '''
const assert = require('assert');
const fields = new Proxy({}, {get(t,k){return t[k] ||= {value:'synthetic', textContent:'', close(){this.closed=true;}};}});
function byId(k){return fields[k];}
const saved = {context:{run:{id:1}},url:'/bound',configuration:{repository_identity:'r',config_digest:'c'}};
let commitIdentityContext=saved;
let refreshed=0, submitted=0;
function assertOwnerDeliveryActionCurrent(c){assert.strictEqual(c,saved.context);}
function productActionMessage(e){return e.message;}
async function api(url, args){submitted++; assert.equal(url,'/bound');
 assert.equal(args.body.name,'synthetic'); assert.equal(args.body.confirmation,'SAVE_REPOSITORY_GIT_IDENTITY');
 if(FAILURE) throw new Error('Config lock held'); return {review:{next_action:'Review Commit'}};}
async function loadOwnerDelivery(run, force){assert.equal(run.id,1);assert.equal(force,true);refreshed++;}
async function performAction(k,b,l,fn){try {await fn();} catch(e) {if(!FAILURE) throw e;}}
'''.replace("FAILURE", json.dumps(failure))
    result = node(harness + function("saveCommitIdentity") + '''
(async()=>{await saveCommitIdentity({preventDefault(){}}); process.stdout.write(JSON.stringify({
 submitted,refreshed,closed:!!fields['commit-identity-dialog'].closed,error:fields['commit-identity-error'].textContent}));})();
''')
    assert result["submitted"] == result["refreshed"] == 1
    assert result["closed"] is not failure
    assert result["error"] == ("Config lock held" if failure else "")


def test_current_build_identity_matches_packaged_schema():
    import plistlib

    from twos_runtime import __version__
    from twos_runtime.maintenance import TARGET_SCHEMA
    from scripts import build_macos
    source = Path(build_macos.__file__).read_text()
    assert __version__ == "1.0.2"
    assert '"build_version": "101.50"' in source
    assert TARGET_SCHEMA == "vol20.002"
    assert '"CFBundleVersion": provenance["build_version"]' in source
    assert "build-{provenance['build_version']}.dmg" in source

    # When the actual frozen artifact gate is enabled, bind the build expectation
    # to the packaged identity too; checking the builder text alone is insufficient.
    if app := os.environ.get("TWOS_TEST_MACOS_APP"):
        contents = Path(app) / "Contents"
        info = plistlib.loads((contents / "Info.plist").read_bytes())
        provenance = json.loads((contents / "Resources/source-provenance.json").read_text())
        assert info["CFBundleShortVersionString"] == __version__
        assert info["CFBundleVersion"] == provenance["build_version"] == "101.50"
        assert info["TWOSSourceCommit"] == provenance["source_commit"]
        assert info["TWOSSourceInputSHA256"] == provenance["source_input_sha256"]
