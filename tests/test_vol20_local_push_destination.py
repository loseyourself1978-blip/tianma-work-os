"""Scoped setup keeps immutable Commit evidence and the independent Push gates."""
import hashlib
import json
import os
from pathlib import Path
from dataclasses import replace

import pytest
from sqlalchemy import select
import tests.test_self_hosting as base
from tests.test_vol19_owner_commit_push_delivery import _canonical_applied_delivery, _commit_delivery, _git, _bare_ref, _error_code
from twos_runtime.models import AuditEvent, LocalCommitExecution
import twos_runtime.local_push_destination as destination


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    home = tmp_path / 'home'; home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    for key in tuple(os.environ):
        if key.startswith('GIT_'): monkeypatch.delenv(key)
    create = base.create_app
    data = tmp_path / 'installed-data'; data.mkdir(mode=0o700)
    monkeypatch.setattr(base, 'create_app', lambda settings, **kw: create(settings=replace(settings, data_root=data), **kw))


def snapshot(f):
    with f.client.app.state.session_factory() as session:
        rows = session.scalars(select(LocalCommitExecution)).all()
        receipts = [(r.receipt_digest, r.post_commit_evidence_json) for r in rows]
    return (_git(f.source_repo, 'rev-parse', 'HEAD'), (f.source_repo/'.git/index').read_bytes(),
            {str(p.relative_to(f.source_repo)): p.read_bytes() for p in f.source_repo.rglob('*') if p.is_file() and '.git' not in p.parts}, receipts)


def setup(f, commit):
    url = f"/api/local-commits/{commit['id']}/local-test-destination"
    review = f.client.get(url, headers=f.headers)
    assert review.status_code == 200, review.text
    payload = {'confirmation': 'CREATE_AND_BIND_LOCAL_TEST_DESTINATION', 'expected_preview_digest': review.json()['preview_digest']}
    return url, review.json(), payload


def test_setup_and_independent_local_push_preserve_commit(tmp_path):
    with _canonical_applied_delivery(tmp_path/'delivery', without_origin=True) as f:
        _, _, commit = _commit_delivery(f)
        before = snapshot(f)
        url, review, payload = setup(f, commit)
        target = Path(review['destination'])
        assert not target.exists()
        response = f.client.post(url, headers=f.headers, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()['configured']
        assert snapshot(f) == before
        assert _bare_ref(target) == commit['parent_oid']
        assert _git(f.source_repo, 'remote', 'get-url', 'origin') == str(target)
        # Setup did not copy/send the delivery Commit or private Git config/hooks.
        assert destination._run_git(target, 'cat-file', '-e', commit['commit_oid'], check=False).returncode != 0
        assert not (target/'hooks').exists()
        assert f.client.post(url, headers=f.headers, json=payload).json()['configured']
        plan_url = f"/api/local-commits/{commit['id']}/push-plans"
        reviewed = f.client.post(plan_url, headers=f.headers, json={})
        assert reviewed.status_code == 200, reviewed.text
        plan = reviewed.json()['push_plan']
        assert reviewed.json()['actions']['can_approve_push_plan'], reviewed.text
        assert plan['remote_old_sha'] == commit['parent_oid']
        assert plan['owner_destination'] == str(target)
        attempt_url = f"/api/push-plans/{plan['id']}/push-attempts"
        denied = f.client.post(attempt_url, headers=f.headers, json={'confirmation':'PUSH_TO_ORIGIN_MAIN', 'expected_plan_digest':plan['advanced']['plan_digest'], 'expected_approval_digest':'0'*64})
        assert denied.status_code == 409
        assert _bare_ref(target) == commit['parent_oid']
        approval = f.client.post(f"/api/push-plans/{plan['id']}/approvals", headers=f.headers, json={'confirmation':'APPROVE_PUSH_PLAN','expected_plan_digest':plan['advanced']['plan_digest'],'expected_plan_version':plan['version']})
        assert approval.status_code == 200, approval.text
        assert _bare_ref(target) == commit['parent_oid']
        pushed = f.client.post(attempt_url, headers=f.headers, json={'confirmation':'PUSH_TO_ORIGIN_MAIN','expected_plan_digest':plan['advanced']['plan_digest'],'expected_approval_digest':approval.json()['push_approval']['advanced']['approval_digest']})
        assert pushed.status_code == 200, pushed.text
        assert pushed.json()['delivery_result']['complete'], pushed.text
        assert _bare_ref(target) == commit['commit_oid']
        assert snapshot(f) == before


@pytest.mark.parametrize('problem', ['lock','stale','drift','existing','symlink','foreign','extra_input','existing_remote','config_drift_after','target_changed_after'])
def test_setup_boundaries(tmp_path, problem):
    with _canonical_applied_delivery(tmp_path/'delivery', without_origin=True) as f:
        _, _, commit = _commit_delivery(f)
        before = snapshot(f)
        config = f.source_repo/'.git/config'; original = config.read_bytes()
        url, review, payload = setup(f, commit)
        target = Path(review['destination'])
        if problem == 'lock': (f.source_repo/'.git/config.lock').write_text('other owner lock')
        if problem == 'stale': payload['expected_preview_digest'] = '0'*64
        if problem == 'drift': (f.source_repo/'new-untracked').write_text('preserve')
        if problem == 'existing': target.parent.mkdir(); target.mkdir()
        if problem == 'symlink': target.parent.symlink_to(tmp_path/'home', target_is_directory=True)
        if problem == 'foreign': url = url.replace(commit['id'], 'commit-other')
        if problem == 'extra_input': payload['destination'] = 'https://example.invalid'
        if problem == 'existing_remote': _git(f.source_repo, 'remote','add','origin','https://example.invalid/private')
        if problem.endswith('_after'):
            assert f.client.post(url, headers=f.headers, json=payload).status_code == 200
            if problem == 'config_drift_after': _git(f.source_repo,'config','user.name','Changed synthetic name')
            else:
                target.rename(target.with_suffix('.retained'))
                target.mkdir(); destination._seed(f.source_repo, target, commit['parent_oid'])
            r = f.client.post(f"/api/local-commits/{commit['id']}/push-plans", headers=f.headers, json={})
            assert r.status_code == 409 or not r.json()['actions']['can_approve_push_plan'], r.text
        else:
            r = f.client.post(url, headers=f.headers, json=payload)
            assert r.status_code in (403,404,409,422), r.text
            if problem not in ('existing_remote',): assert config.read_bytes() == original
            if problem == 'lock':
                assert (f.source_repo/'.git/config.lock').read_text() == 'other owner lock'
                (f.source_repo/'.git/config.lock').unlink() # only our disposable test lock
                assert f.client.post(url,headers=f.headers,json=payload).status_code == 200
        assert _git(f.source_repo,'rev-parse','HEAD') == before[0]
        assert (f.source_repo/'.git/index').read_bytes() == before[1]


def test_atomic_failure_retry_csrf_auth_and_restart(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from twos_runtime.app import create_app
    from tests.test_self_hosting import OWNER_PASSWORD
    with _canonical_applied_delivery(tmp_path/'delivery', without_origin=True) as f:
        _, _, commit = _commit_delivery(f)
        before = snapshot(f)
        url, review, payload = setup(f, commit)
        config = f.source_repo/'.git/config'; original = config.read_bytes()
        for headers in ({'Origin':'https://foreign.invalid'}, {'Sec-Fetch-Site':'cross-site'}):
            assert f.client.post(url, headers=headers, json=payload).status_code == 403
        replace_file = os.replace
        def fail_publish(src, dst, **kwargs):
            if str(src) == 'config.lock': raise OSError('synthetic write failure')
            return replace_file(src, dst, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(destination.os, 'replace', fail_publish)
            response = f.client.post(url, headers=f.headers, json=payload)
        assert response.status_code == 409, response.text
        assert _error_code(response) == 'LOCAL_DESTINATION_SETUP_FAILED'
        assert config.read_bytes() == original
        assert snapshot(f) == before
        assert not (f.source_repo/'.git/config.lock').exists()
        assert f.client.post(url, headers=f.headers, json=payload).json()['configured']
        assert snapshot(f) == before
        settings = f.client.app.state.settings
        f.client.post('/api/auth/logout')
        assert f.client.post(url,json=payload).status_code == 401
    with TestClient(create_app(settings, start_scheduler=False)) as restarted:
        assert restarted.post('/api/auth/login',json={'username':'owner','password':OWNER_PASSWORD}).status_code == 200
        assert restarted.get(url).json()['configured']
        reviewed = restarted.post(f"/api/local-commits/{commit['id']}/push-plans",json={})
        assert reviewed.status_code == 200, reviewed.text
        assert reviewed.json()['actions']['can_approve_push_plan']


def test_gui_controller_keeps_setup_explicit_and_failures_visible():
    from tests.test_vol19_guided_acceptance_corrections import function, node
    harness = r'''
const assert=require('node:assert/strict');
const state={pending:new Set(),ownerPushReviewAttempts:{'commit-1':{phase:'failed'}}};
let localPushDestinationContext=null, calls=[],shouldFail=false,refreshes=0;
const el={};function byId(id){return el[id] ||= {hidden:true,disabled:false,dataset:{},textContent:'',showModal(){this.open=true},close(){this.open=false},focus(){}};}
class ApiError extends Error{};
function productActionMessage(e){return e.message;}
function ownerDeliveryActionContext(){return {run:{id:1},parts:{commitExecution:{id:'commit-1'}}};}
function ownerDeliveryRecordId(v){return v.id;}
function assertOwnerDeliveryActionCurrent(){}
function handleExpiredSession(){}
function renderWorkspace(){}
async function loadOwnerDelivery(){refreshes++;}
const value={commit_id:'commit-1',project:'Synthetic project',task:'Synthetic task',repository:'/isolated/source',destination:'/isolated/data/local-push-tests/commit-1.git',parent_sha:'a',commit_sha:'b',preview_digest:'c'};
async function api(url,options){calls.push({url,options});if(shouldFail)throw new Error('GIT_CONFIG_LOCKED: Another operation holds the lock.');return {...value,configured:!!options};}
'''
    code = harness + function('openLocalPushDestination') + function('saveLocalPushDestination') + r'''
(async()=>{
await openLocalPushDestination();assert.equal(calls.length,1);assert.equal(calls[0].options,undefined);
assert.equal(byId('local-push-destination-dialog').open,true);
assert.equal(byId('local-push-target').textContent,value.destination);
assert.equal(byId('save-local-push-destination').disabled,false);
shouldFail=true;await saveLocalPushDestination({preventDefault(){}});
assert.equal(byId('local-push-destination-dialog').open,true);
assert.match(byId('local-push-error').textContent,/GIT_CONFIG_LOCKED/);
assert.equal(byId('save-local-push-destination').disabled,false);
shouldFail=false;await saveLocalPushDestination({preventDefault(){}});
assert.equal(byId('local-push-destination-dialog').open,false);
assert.match(byId('local-push-setup-feedback').textContent,/No Push occurred/);
assert.equal(refreshes,2);assert.equal(calls.length,3);
assert.ok(calls.every(c=>c.url.endsWith('/local-test-destination')));
assert.equal(calls[2].options.body.confirmation,'CREATE_AND_BIND_LOCAL_TEST_DESTINATION');
process.stdout.write(JSON.stringify({passed:true}));
})().catch(e=>{console.error(e);process.exit(1)});
'''
    assert node(code)['passed']
