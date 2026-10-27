"""Push review errors stay at the action; review never authorizes transport."""
import hashlib
import json
import os
from pathlib import Path
import re

import pytest

from tests.test_vol19_owner_commit_push_delivery import (
    _canonical_applied_delivery, _commit_delivery, _git, _bare_ref, _error_code,
)
from tests.test_vol19_guided_acceptance_corrections import function, node
import twos_runtime.push_delivery as push


@pytest.fixture(autouse=True)
def private_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for key in tuple(os.environ):
        if key.startswith("GIT_"):
            monkeypatch.delenv(key)


@pytest.mark.parametrize("problem,expected", [
    ("missing_origin", "ORIGIN_UNAVAILABLE"),
    ("missing_path", "REMOTE_URL_UNSAFE"),
    ("missing_branch", "REMOTE_MAIN_UNAVAILABLE"),
    ("unsupported", "REMOTE_URL_UNSAFE"),
    ("multiple", "REMOTE_URL_UNSAFE"),
])
def test_review_boundary_failure_is_read_only_and_manual_retry_works(tmp_path, problem, expected):
    with _canonical_applied_delivery(tmp_path / "delivery") as f:
        _, _, commit = _commit_delivery(f)
        url = f"/api/local-commits/{commit['id']}/push-plans"
        config = f.source_repo / ".git/config"
        before_config = config.read_bytes()
        before_index = (f.source_repo / ".git/index").read_bytes()
        before_ref = _bare_ref(f.origin)
        if problem == "missing_origin":
            _git(f.source_repo, "remote", "remove", "origin")
        elif problem == "missing_path":
            _git(f.source_repo, "remote", "set-url", "origin", str(tmp_path / "absent.git"))
        elif problem == "unsupported":
            _git(f.source_repo, "remote", "set-url", "origin", "ext::forbidden")
        elif problem == "multiple":
            _git(f.source_repo, "config", "--add", "remote.origin.pushurl", str(f.origin))
            _git(f.source_repo, "config", "--add", "remote.origin.pushurl", str(tmp_path / "other.git"))
        else:
            _git(f.origin, "update-ref", "-d", "refs/heads/main")
        response = f.client.post(url, headers=f.headers, json={})
        assert response.status_code == 409, response.text
        assert _error_code(response) == expected
        assert _git(f.source_repo, "rev-parse", "HEAD") == commit["commit_oid"]
        assert (f.source_repo / ".git/index").read_bytes() == before_index
        if problem == "missing_origin":
            status = f.client.get(url, headers=f.headers).json()
            assert status["action_state"] == "PUSH_BLOCKED"
            assert status["readiness"]["blockers"][0]["code"] == expected
            assert status["push_plan"] is None
            assert not status["actions"]["can_approve_push_plan"]
            assert not status["actions"]["can_confirm_push"]
            assert status["actions"]["can_review_push_plan"]
        # Restore only this disposable fixture's exact previous state.
        config.write_bytes(before_config)
        _git(f.source_repo, "update-ref", "refs/remotes/origin/main", before_ref)
        if problem == "missing_branch":
            _git(f.origin, "update-ref", "refs/heads/main", before_ref)
        reviewed = f.client.post(url, headers=f.headers, json={})
        assert reviewed.status_code == 200, reviewed.text
        plan = reviewed.json()["push_plan"]
        assert plan["owner_destination"] == str(f.origin.resolve())
        assert plan["local_commit_sha"] == commit["commit_oid"]
        assert plan["remote_old_sha"] == before_ref
        assert plan["remote_new_sha"] == commit["commit_oid"]
        assert plan["checks"]["index_clean"]
        assert _bare_ref(f.origin) == before_ref
        assert not reviewed.json()["actions"]["can_confirm_push"]


def test_entry_uses_packaged_content_digests_without_cache_purge(tmp_path):
    with _canonical_applied_delivery(tmp_path / "delivery") as f:
        page = f.client.get("/twos")
        assert page.status_code == 200
        assert page.headers["cache-control"] == "no-store"
        urls = re.findall(r'(?:src|href)="(/static_cockpit/[^" ]+\?sha256=[a-f0-9]{64})"', page.text)
        assert len(urls) == 2
        for url in urls:
            asset = f.client.get(url)
            assert asset.status_code == 200
            assert hashlib.sha256(asset.content).hexdigest() == url.split("sha256=")[1]
        assert "?v=1.0.1" not in page.text


HARNESS = r'''
const assert = require('node:assert/strict');
class ApiError extends Error { constructor(status,code,message){super(message);this.status=status;this.code=code;this.category='product';} }
const AUTH_STATES={SIGNED_IN:'in',SIGNED_OUT:'out'};
const state={auth:'in',pending:new Set(),ownerPushReviewAttempts:{},ownerDeliveryRequestSequences:{},ownerDeliveryProjections:{},taskSelectionEpoch:1};
const base={run_id:1,commit_delivery:{execution:{id:'commit-1',commit_oid:'abc'}},push_delivery:{actions:{can_review_push_plan:true}}};
let parts={projection:base,commitExecution:base.commit_delivery.execution,pushDelivery:base.push_delivery,pushActions:base.push_delivery.actions};
let calls=[],renders=0,expired=false,release;
const elements=new Proxy({}, {get(t,k){return t[k] ||= {textContent:'',hidden:false,dataset:{},setAttribute(){},removeAttribute(){},scrollIntoView(){},disabled:false};}});
function objectRecord(x){return x&&typeof x==='object'?x:{};}
function ownerDeliveryRecordId(x){return objectRecord(x).id;}
function applyPlanTextList(x){return Array.isArray(x)?x.map(v=>typeof v==='string'?v:v.message):[];}
function appendTextList(el,x){el.textContent=x.join(' ');}
function ownerDeliveryActionContext(){return {run:{id:1},parts,epoch:state.taskSelectionEpoch};}
function assertOwnerDeliveryActionCurrent(c){if(c.epoch!==state.taskSelectionEpoch)throw new ApiError(409,'STALE','Task changed');}

function handleExpiredSession(){expired=true;state.auth='out';state.ownerPushReviewAttempts={};}
function renderWorkspace(){renders++;renderOwnerPushReviewFeedback(parts);}
const response={local_commit_execution_id:'commit-1',push_plan:{id:'plan-1',local_commit_sha:'abc'},actions:{can_approve_push_plan:true},confirmation:{state:'blocked'}};
async function api(url,request){calls.push({url,request});return await new Promise((yes,no)=>{release={yes,no};});}
'''


def controller(scenario):
    helpers = ''.join(function(n) for n in (
        'ownerPushReviewAttempt','resolveOwnerPushReviewAttempt',
        'renderOwnerPushReviewFeedback','reviewOwnerPushPlan','productActionMessage',
    ))
    return node(HARNESS + helpers + '\n(async()=>{' + scenario + '\n})().catch(e=>{console.error(e);process.exit(1)});')


@pytest.mark.parametrize('code,status', [('ORIGIN_UNAVAILABLE',409),('REQUEST_TIMEOUT',0),('NETWORK_ERROR',0),('SERVER_ERROR',500),('REPOSITORY_MUTATION_ACTIVE',409)])
def test_visible_failure_survives_finally_and_single_manual_retry(code,status):
    result = controller(f'''
const pending=reviewOwnerPushPlan();
assert.equal(elements.pushReviewFeedback.dataset.phase,'checking');
await reviewOwnerPushPlan();assert.equal(calls.length,1);
release.no(new ApiError({status},{json.dumps(code)},'Specific visible blocker'));
await pending;
assert.equal(state.pending.size,0);
assert.equal(elements.pushReviewFeedback.dataset.phase,'failed');
assert.match(elements.pushReviewFeedback.textContent,/Specific visible blocker/);
assert.equal(elements.pushGateStatus.textContent,'PUSH REVIEW BLOCKED');
renderWorkspace();assert.match(elements.pushReviewFeedback.textContent,/Specific visible blocker/);
const retry=reviewOwnerPushPlan();release.yes(response);await retry;
assert.equal(calls.length,2);
assert.equal(state.ownerDeliveryProjections['1'].push_delivery.push_plan.id,'plan-1');
assert.equal(elements.pushReviewFeedback.dataset.phase,'reviewed');
assert.ok(calls.every(c=>c.request.method==='POST'&&c.url==='/api/local-commits/commit-1/push-plans'));
process.stdout.write(JSON.stringify({{requests:calls.length}}));
''')
    assert result['requests']==2


def test_session_expiry_uses_login_and_never_claims_review():
    assert controller('''const p=reviewOwnerPushPlan();release.no(new ApiError(401,'SESSION','Expired'));await p;
assert.equal(expired,true);assert.equal(state.auth,'out');assert.equal(calls.length,1);
process.stdout.write(JSON.stringify({expired}));''')['expired']


@pytest.mark.parametrize('change', ['response.local_commit_execution_id="other"','response.push_plan=null','state.taskSelectionEpoch++'])
def test_mismatched_success_cannot_enable_approval(change):
    result=controller('''const p=reviewOwnerPushPlan();'''+change+''';release.yes(response);await p;
assert.equal(state.ownerDeliveryProjections['1'],undefined);
assert.equal(state.ownerPushReviewAttempts['commit-1'].phase,'failed');
process.stdout.write(JSON.stringify({blocked:true}));''')
    assert result['blocked']


def test_canonical_refresh_reconciles_saved_plan_without_repeat_post():
    result=controller('''const p=reviewOwnerPushPlan();release.no(new ApiError(0,'NETWORK_ERROR','Response lost'));await p;
resolveOwnerPushReviewAttempt({...base,push_delivery:response});
assert.equal(state.ownerPushReviewAttempts['commit-1'],undefined);
assert.equal(calls.length,1);process.stdout.write(JSON.stringify({reconciled:true}));''')
    assert result['reconciled']


def test_real_backend_origin_error_remains_readable_in_actual_error_formatter(tmp_path):
    with _canonical_applied_delivery(tmp_path / "delivery") as f:
        _, _, commit = _commit_delivery(f)
        _git(f.source_repo, "remote", "remove", "origin")
        response = f.client.post(f"/api/local-commits/{commit['id']}/push-plans", headers=f.headers, json={})
        error = response.json()["error"]["details"]
        assert error["code"] == "ORIGIN_UNAVAILABLE"
        assert len(error["message"]) <= 220
        result = controller("const p=reviewOwnerPushPlan();const e=new ApiError(409,'ORIGIN_UNAVAILABLE'," + json.dumps(error["message"]) + ");e.category='twos';release.no(e);await p;assert.ok(elements.pushReviewFeedback.textContent.includes(e.message));process.stdout.write(JSON.stringify({readable:true}));")
        assert result["readable"]


def test_reviewed_plan_waits_for_approval_without_masking_real_blockers():
    result = node(HARNESS + function("ownerPushReviewAttempt") + function("canonicalPushState") + r'''
state.ownerPushConfirmationState={};
function ownerPushConfirmationRequestInFlight(){return false;}
function ownerPushConfirmationUncertaintyActive(){return false;}
function ownerPushConfirmationProjectionRelevant(){return true;}
let partsForState={commitExecution:{id:'commit-1'},pushConfirmation:{state:'blocked'},pushPlan:{id:'plan-1'},pushExecution:{},pushActions:{can_approve_push_plan:true}};
assert.equal(canonicalPushState(partsForState),'PUSH_APPROVAL_REQUIRED');
partsForState.pushActions.can_approve_push_plan=false;
assert.equal(canonicalPushState(partsForState),'BLOCKED');
partsForState.pushActions.can_approve_push_plan=true;partsForState.pushExecution={id:'execution-1'};
assert.equal(canonicalPushState(partsForState),'BLOCKED');
partsForState.pushExecution={};state.ownerPushReviewAttempts['commit-1']={phase:'failed'};
assert.equal(canonicalPushState(partsForState),'BLOCKED');
process.stdout.write(JSON.stringify({matched:true}));
''')
    assert result['matched']
