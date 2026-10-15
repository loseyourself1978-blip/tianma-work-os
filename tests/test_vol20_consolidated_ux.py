"""Integrated UX contracts; synthetic providers, isolated Git and no Owner data.

Actual packaged GUI clicks are separately recorded in the local evidence package.
"""
from dataclasses import replace
import json
from pathlib import Path
import shutil

import pytest
from sqlalchemy import select

from tests.test_vol19_guided_acceptance_corrections import function, node
from tests.test_vol19_guided_first_delivery import (
    environment, local_runner, make_client, init_and_login, CHOICE,
    check_and_save, create_task, approve_pack, start_codex_run, wait_for_run,
)
from twos_runtime import tool_recovery, guided_delivery, project_workspaces
from twos_runtime.models import GuidedToolConfiguration, CodexInstructionPack, CodexRun
from twos_runtime.result_intake import canonical_sha256


@pytest.fixture(autouse=True)
def private_environment(tmp_path, monkeypatch):
    home = tmp_path / 'home'; home.mkdir(mode=0o700)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('CODEX_HOME', str(home / '.codex'))
    import os
    for key in tuple(os.environ):
        if key.startswith('GIT_'): monkeypatch.delenv(key)


def choice(client, path):
    data = client.get('/api/guided-tool-setup').json()
    selected = next(v for v in data['tool_choices'] if v['path'] == str(path.resolve()))
    return {**CHOICE, 'executable_id': selected['id'],
            'verifier_digest': data['diagnosis']['verifier_digest'],
            'confirm_verifier_change': True}


def test_passive_missing_executable_and_verifier_change_are_not_configuration_loss(tmp_path, monkeypatch):
    repo, runner, verifier = environment(tmp_path)
    with make_client(tmp_path, repo, runner, local_verification_command=verifier) as client:
        init_and_login(client); saved = check_and_save(client)
        runner.rename(runner.with_name('retained-old-tool'))
        Path(verifier[1]).write_text(Path(verifier[1]).read_text() + '\n# synthetic changed identity\n')
        def forbidden(*a, **kw): raise AssertionError('Passive diagnosis must not execute anything')
        with monkeypatch.context() as patch:
            import subprocess
            patch.setattr(subprocess, 'run', forbidden)
            with client.app.state.session_factory() as session:
                row = session.get(GuidedToolConfiguration, saved['id'])
                view = guided_delivery.configuration_out(session, row, settings=client.app.state.settings)
                diag = view['diagnosis']
                assert diag['configuration_saved'] and view['confirmed'] and not view['ready']
                assert {r['code'] for r in diag['reasons']} == {'EXECUTABLE_MISSING', 'VERIFIER_CHANGED'}
                assert diag['provider_request_performed'] is False
                assert diag['historical_delivery_unchanged'] is True
                assert view['last_successful_readiness_check']


def test_trusted_selection_is_explicit_durable_and_used_by_future_execution(tmp_path):
    repo, original, verifier = environment(tmp_path)
    candidate = Path.home() / 'Applications/Codex.app/Contents/Resources/codex'
    candidate.parent.mkdir(parents=True)
    shutil.copy2(original, candidate)
    with make_client(tmp_path, repo, original, timeout=30, local_verification_command=verifier) as client:
        init_and_login(client)
        before = (repo / '.git/config').read_bytes()
        payload = choice(client, candidate)
        result = client.post('/api/guided-tool-setup/check', json=payload)
        assert result.status_code == 200, result.text
        config = result.json()['configuration']
        assert config['ready'] and not config['confirmed']
        assert config['executable'] == str(candidate)
        assert not candidate.with_suffix('.run-effect').exists()
        save = client.post('/api/guided-tool-setup/save', json={'configuration_id': config['id']})
        assert save.status_code == 200, save.text
        assert save.json()['configuration']['confirmed']
        task = create_task(client)
        with client.app.state.session_factory() as session:
            scoped = project_workspaces.task_settings(session, client.app.state.settings, task, 1)
            assert scoped.codex_executable == str(candidate)
        original.rename(original.with_name('retained-original'))
        pack = client.post(f'/api/tasks/{task}/first-delivery/prepare')
        assert pack.status_code == 200, pack.text
        pack = pack.json(); approve_pack(client, {}, task, pack['id'])
        run = start_codex_run(client, {}, task, pack)
        assert run.status_code == 200, run.text
        completed = wait_for_run(client, {}, run.json()['id'], {'completed', 'failed'}, timeout=60)
        assert completed['status'] == 'completed', completed
        assert candidate.with_suffix('.reasoning').is_file()
        assert (repo / '.git/config').read_bytes() == before
        # Changing future configuration must not invalidate an executed Pack.
        payload = choice(client, candidate); payload['reasoning_effort'] = 'max'
        checked = client.post('/api/guided-tool-setup/check', json=payload)
        assert checked.status_code == 200, checked.text
        saved = client.post('/api/guided-tool-setup/save', json={'configuration_id': checked.json()['configuration']['id']})
        assert saved.status_code == 200, saved.text
        with client.app.state.session_factory() as session:
            assert session.get(CodexInstructionPack, pack['id']).status == 'approved'
            assert session.get(CodexRun, run.json()['id']).status == 'completed'
        settings = client.app.state.settings
    from fastapi.testclient import TestClient
    from twos_runtime.app import create_app
    from tests.test_self_hosting import OWNER_PASSWORD
    with TestClient(create_app(settings, start_scheduler=False)) as restarted:
        assert restarted.post('/api/auth/login', json={'username':'owner', 'password':OWNER_PASSWORD}).status_code == 200
        data = restarted.get('/api/guided-tool-setup').json()
        assert data['saved_configuration']['executable'] == str(candidate)
        assert data['saved_configuration']['confirmed']
        candidate.rename(candidate.with_name('retained-selected'))
        with restarted.app.state.session_factory() as session:
            scoped = tool_recovery.saved_settings(session, settings, 1)
            assert scoped.codex_executable == str(candidate)  # no silent fallback
        data = restarted.get('/api/guided-tool-setup').json()
        assert not data['saved_configuration']['ready']
        assert 'EXECUTABLE_MISSING' in {r['code'] for r in data['diagnosis']['reasons']}


@pytest.mark.parametrize('fault', ['stale_selection','missing_selection','verifier_unconfirmed','verifier_stale','cross_site','bad_origin'])
def test_selection_and_verifier_failure_never_probe_or_save(tmp_path, monkeypatch, fault):
    repo, runner, verifier = environment(tmp_path)
    with make_client(tmp_path, repo, runner, local_verification_command=verifier) as client:
        init_and_login(client); old = check_and_save(client)
        payload = choice(client, runner); headers = {}
        if fault == 'stale_selection': runner.write_text(runner.read_text() + '\n# changed\n')
        elif fault == 'missing_selection': payload['executable_id'] = '0' * 64
        elif fault.startswith('verifier_'):
            Path(verifier[1]).write_text(Path(verifier[1]).read_text() + '\n# changed\n')
            if fault == 'verifier_unconfirmed':
                payload = choice(client, runner); payload['confirm_verifier_change'] = False
        elif fault == 'cross_site': headers['Sec-Fetch-Site'] = 'cross-site'
        elif fault == 'bad_origin': headers['Origin'] = 'https://untrusted.invalid'
        import twos_runtime.app as module
        monkeypatch.setattr(module, 'verify_codex_connection', lambda *a, **kw: pytest.fail('Invalid selection must not probe'))
        response = client.post('/api/guided-tool-setup/check', json=payload, headers=headers)
        assert response.status_code in (403,409), response.text
        with client.app.state.session_factory() as session:
            assert len(session.scalars(select(GuidedToolConfiguration)).all()) == 1
            assert session.get(GuidedToolConfiguration, old['id']).confirmed_at


def test_candidates_exclude_mutable_workspace_and_unsafe_permissions(tmp_path):
    repo, runner, verifier = environment(tmp_path)
    with make_client(tmp_path, repo, runner, local_verification_command=verifier) as client:
        settings = client.app.state.settings
        assert str(runner) in {x['path'] for x in tool_recovery.candidates(settings)}
        runner.chmod(0o777)
        assert str(runner) not in {x['path'] for x in tool_recovery.candidates(settings)}
        unsafe = repo / 'codex'; shutil.copy2(runner, unsafe); unsafe.chmod(0o755)
        assert str(unsafe) not in {x['path'] for x in tool_recovery.candidates(replace(settings, codex_executable=str(unsafe)))}


FLOW_HARNESS = r'''
const assert=require('node:assert/strict');
const state={pending:new Set(),ownerPushReviewAttempts:{}};
const nodes={}; function byId(id){return nodes[id] ||= {hidden:false,disabled:false,dataset:{},textContent:''};}
const elements={reviewPushPlan:{},approvePushPlan:{},confirmOwnerPush:{},pushReviewFeedback:{},pushNextAction:{}};
function objectRecord(v){return v && typeof v==='object' ? v : {};}
function ownerDeliveryRecordId(v){return objectRecord(v).id;}
function ownerPushReviewAttempt(p){return state.ownerPushReviewAttempts[ownerDeliveryRecordId(p.commitExecution)] || {};}
let parts={commitExecution:{id:'commit-1'},pushDelivery:{readiness:{blockers:[{code:'ORIGIN_UNAVAILABLE'}]}}};
'''


def test_missing_destination_is_primary_before_review_and_delivered_has_two_snapshot_times():
    code = FLOW_HARNESS + function('ownerPushNeedsDestination') + function('renderPushDestinationState') + r'''
assert.equal(ownerPushNeedsDestination(parts),true);
renderPushDestinationState(parts,'PUSH_BLOCKED');
assert.equal(nodes['push-destination-prerequisite'].hidden,false);
assert.equal(elements.reviewPushPlan.hidden,true);
assert.match(elements.pushNextAction.textContent,/Configure/);
parts.pushDelivery.readiness.blockers=[];
parts.pushPlan={id:'plan-1',created_at:'2026-09-28T01:00:00Z',checks:{ahead:1,behind:0}};
parts.pushExecution={id:'push-1',remote_receipt_verified:true,finished_at:'2026-09-28T02:00:00Z',post_push:{ahead:0,behind:0,complete:true}};
renderPushDestinationState(parts,'DELIVERED');
assert.equal(nodes['push-preflight-time'].textContent,parts.pushPlan.created_at);
assert.equal(nodes['push-post-time'].textContent,parts.pushExecution.finished_at);
assert.equal(nodes['push-post-ahead-behind'].textContent,'0 / 0 · complete');
assert.equal(nodes['local-push-setup-feedback'].hidden,true);
for(const name of ['reviewPushPlan','approvePushPlan','confirmOwnerPush','pushReviewFeedback'])assert.equal(elements[name].hidden,true);
assert.match(elements.pushNextAction.textContent,/no repeat action/);
delete parts.pushPlan.created_at;delete parts.pushExecution.finished_at;
renderPushDestinationState(parts,'DELIVERED');
assert.equal(nodes['push-preflight-time'].textContent,'Not recorded');
assert.equal(nodes['push-post-time'].textContent,'Not recorded');
parts.pushExecution.remote_receipt_verified=false;
renderPushDestinationState(parts,'PUSH_UNVERIFIED');
assert.equal(nodes['push-post-ahead-behind'].textContent,'Not verified');
process.stdout.write(JSON.stringify({passed:true}));
'''
    assert node(code)['passed']


def test_flow_context_is_bound_to_installation_and_account():
    code = r'''
const assert=require('node:assert/strict');
let task={id:8};const state={health:{installation_id:'isolated-install'},user:{id:4},selectedActivityRunId:7,flowView:'history'};
const stored=new Map();const window={location:{origin:'local'},localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)}};
function objectRecord(v){return v||{};}function selectedTask(){return task;}
''' + ''.join(function(n) for n in ('flowContextKey','readFlowContext','saveFlowContext')) + r'''
saveFlowContext();assert.deepEqual(readFlowContext(),{task_id:8,run_id:7,view:'history'});
state.user.id=5;assert.equal(readFlowContext(),null);
state.user.id=4;state.health.installation_id='different';assert.equal(readFlowContext(),null);
state.health.installation_id='isolated-install';assert.equal(readFlowContext().task_id,8);
window.localStorage.getItem=()=>{throw Error('storage unavailable')};assert.equal(readFlowContext(),null);
process.stdout.write(JSON.stringify({passed:true}));
'''
    assert node(code)['passed']


@pytest.mark.parametrize('modal', ['destination','identity'])
def test_configuration_modal_opens_before_inspection_and_ignores_cancelled_response(modal):
    code = r'''
const assert=require('node:assert/strict');
const state={pending:new Set()};let localPushDestinationContext=null,commitIdentityContext=null;
const elements={configureCommitIdentity:{}};
const fields={};function byId(id){return fields[id] ||= {value:'',textContent:'',dataset:{},hidden:false,disabled:false,open:false,showModal(){this.open=true},focus(){}};}
const context={run:{id:1},parts:{commitPrerequisitesMet:true,commitExecution:{id:'c'},postApply:{id:'v'}}};
function ownerDeliveryActionContext(){return context;}function ownerDeliveryRecordId(v){return v.id;}
function assertOwnerDeliveryActionCurrent(){};function productActionMessage(e){return e.message;}
function handleExpiredSession(){};class ApiError extends Error{};
let calls=0,resolve;async function api(){calls++;return await new Promise(r=>{resolve=r});}
''' + function('openLocalPushDestination' if modal == 'destination' else 'openCommitIdentity')
    opening = 'openLocalPushDestination' if modal == 'destination' else 'openCommitIdentity'
    dialog = 'local-push-destination-dialog' if modal == 'destination' else 'commit-identity-dialog'
    save = 'save-local-push-destination' if modal == 'destination' else 'save-commit-identity'
    epoch = 'destinationOpenEpoch' if modal == 'destination' else 'identityOpenEpoch'
    saved = 'localPushDestinationContext' if modal == 'destination' else 'commitIdentityContext'
    code += f'''(async()=>{{
const pending={opening}();assert.equal(byId('{dialog}').open,true);assert.equal(byId('{save}').disabled,true);
await {opening}();assert.equal(calls,1); // suppress duplicate clicks
byId('{dialog}').open=false;state.{epoch}++;
resolve({{commit_id:'c',verification_id:'v'}});await pending;
assert.equal(byId('{dialog}').open,false);assert.equal({saved},null);
assert.equal(byId('{save}').disabled,true);
process.stdout.write(JSON.stringify({{passed:true}}));
}})().catch(e=>{{console.error(e);process.exit(1)}});'''
    assert node(code)['passed']


def test_late_tool_inspection_and_save_failure_remain_bound_to_current_task():
    code = r'''
const assert=require('node:assert/strict');
const state={pending:new Set(),taskSelectionEpoch:1,guidedToolTaskEpoch:1,guidedToolEpoch:1};
const nodes={};function byId(id){return nodes[id] ||= {value:'',textContent:'',open:true,disabled:false};}
function renderGuidedToolControls(){};function guidedProjectQuery(){return '?project_id=1';}
function productActionMessage(e){return e.message;}function handleExpiredSession(){};class ApiError extends Error{};
let calls=0,resolve;async function api(){calls++;return await new Promise(r=>{resolve=r});}
async function refreshWorkspace(){throw Error('A failed Save cannot report success');}
''' + function('loadGuidedToolChoice') + function('saveGuidedTool') + r'''
(async()=>{
const pending=loadGuidedToolChoice('opaque-candidate');state.taskSelectionEpoch=2;
resolve({discovery:{models:[]},tool_choices:[]});await pending;
assert.equal(state.guidedToolDiscovery,undefined);
state.guidedToolTaskEpoch=2;state.guidedToolEpoch=3;
state.guidedToolChecked={id:2};api=async()=>{calls++;throw new Error('Configuration lock held');};
await saveGuidedTool();
assert.match(byId('guided-tool-state').textContent,/Configuration lock held/);
assert.match(byId('guided-tool-state').textContent,/prior saved configuration is preserved/);
assert.equal(state.pending.has('save-guided-tool'),false);
assert.equal(calls,2);
process.stdout.write(JSON.stringify({passed:true}));
})().catch(e=>{console.error(e);process.exit(1)});
'''
    assert node(code)['passed']


def test_three_views_keep_exact_action_and_delivered_context_without_network():
    code = r'''
const assert=require('node:assert/strict');
const AUTH_STATES={SIGNED_IN:'in'};const UI_VERSION='1.0.1';
const state={auth:'in',tasks:[{id:1},{id:2}],selectedTaskId:1,taskLoadState:'success',pending:new Set(),health:{installation_id:'isolated',build:{build_version:'101.7'}},user:{id:1},codexStatus:{},firstDeliveryGuide:{task_id:1,stage_index:8}};
let task={id:1},run={id:1},parts={commitExecution:{id:'commit-1'},pushPlan:{},state:'READY'};
const nodes={};function byId(id){return nodes[id] ||= {dataset:{},textContent:'',parentElement:null,hidden:false,appendChild(el){el.parentElement=this},setAttribute(){}};}
const buttons=['setup','work','history'].map(v=>({dataset:{flowView:v},setAttribute(){}}));
const document={querySelectorAll:()=>buttons};const storage=new Map();
const window={location:{origin:'http://isolated'},localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)}};
function objectRecord(v){return v||{}};function selectedTask(){return task;}function currentCodexRun(){return run;}
function ownerDeliveryParts(){return parts;}function ownerDeliveryRecordId(v){return objectRecord(v).id;}
function canonicalPushState(p){return p.state;}function ownerPushNeedsDestination(){return false;}
function api(){throw Error('Rendering must not request readiness or Push');}
''' + ''.join(function(n) for n in ('flowContextKey','readFlowContext','saveFlowContext','renderConsolidatedFlow')) + r'''
renderConsolidatedFlow();
assert.equal(state.flowView,'work');
assert.equal(byId('commit-builder-section').parentElement,byId('flow-action-host'));
assert.equal(byId('flow-work').hidden,false);
parts.state='DELIVERED';state.firstDeliveryGuide.stage_index=10;
renderConsolidatedFlow();assert.equal(state.flowView,'history');
assert.match(byId('result-history-intro').textContent,/Historical Run evidence/);
assert.equal(byId('result-action-label').textContent,'Run-stage action (historical)');
assert.equal(byId('commit-builder-section').parentElement,byId('history-commit-builder-section'));
assert.equal(byId('push-delivery-section').parentElement,byId('flow-delivered-host'));
assert.match(byId('flow-work-summary-text').textContent,/No repeat action/);
state.flowView='setup';renderConsolidatedFlow();
state.flowTaskId=null;state.flowDeliveredTasks={};renderConsolidatedFlow();assert.equal(state.flowView,'setup');
task={id:2};run=null;state.selectedTaskId=2;state.firstDeliveryGuide={task_id:2,stage_index:0};renderConsolidatedFlow();
assert.equal(state.flowView,'setup');assert.equal(byId('first-delivery-guide').parentElement,byId('flow-setup-guide-host'));
assert.equal(byId('flow-work-summary').hidden,false);
assert.match(byId('flow-work-summary-text').textContent,/required setup/);
process.stdout.write(JSON.stringify({passed:true}));
'''
    assert node(code)['passed']


def test_project_destination_summary_is_passive_and_redacts_other_addresses(tmp_path, monkeypatch):
    import subprocess
    from twos_runtime.local_push_destination import project_state
    repo, runner, verifier = environment(tmp_path)
    with make_client(tmp_path, repo, runner, local_verification_command=verifier) as client:
        settings = replace(client.app.state.settings, data_root=tmp_path/'data')
        def git(*args):
            return subprocess.run(['git','-C',str(repo),*args],capture_output=True,check=True)
        assert git('remote').stdout.strip() == b''
        before = (repo/'.git/config').read_bytes()
        assert project_state(settings)['status'] == 'MISSING'
        assert (repo/'.git/config').read_bytes() == before
        target = settings.data_root/'local-push-tests'/'synthetic.git'
        git('remote','add','origin',str(target))
        calls=[];original=subprocess.run
        def watched(argv,*args,**kwargs):
            calls.append(argv)
            assert not any(part in argv for part in ('push','fetch','ls-remote','clone'))
            return original(argv,*args,**kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(subprocess,'run',watched)
            state=project_state(settings)
        assert state['status']=='LOCAL_TEST_CONFIGURED'
        assert state['destination']==str(target) and not state['remote_contacted']
        assert state['configuration_only'] and not target.exists()
        assert calls
        git('remote','set-url','origin','https://synthetic-user:synthetic-secret@example.invalid/private.git')
        result=project_state(settings)
        assert result['status']=='EXISTING_DESTINATION'
        assert 'synthetic-secret' not in json.dumps(result)
        git('config','--add','remote.origin.pushurl','https://example.invalid/one')
        git('config','--add','remote.origin.pushurl','https://example.invalid/two')
        assert project_state(settings)['status']=='UNSUPPORTED'


def test_successful_tool_save_replaces_obsolete_recovery_reasons_in_open_form():
    code=r'''
const assert=require('node:assert/strict');
const state={pending:new Set(),guidedToolChecked:{id:2},guidedToolEpoch:1,taskSelectionEpoch:1,guidedToolTaskEpoch:1};
const nodes={};function byId(id){return nodes[id] ||= {textContent:'old missing executable',disabled:false,hidden:false};}
function guidedProjectQuery(){return '?project_id=1';}function renderGuidedToolControls(){}
function showGuidedConfiguration(v){state.guidedToolChecked=v;}
function appendTextList(el,items,fallback){el.textContent=items.length?items.join(' '):fallback;}
async function api(){return {configuration:{id:2,confirmed:true,ready:true,diagnosis:{reasons:[],verifier_changed:false}}};}
async function refreshWorkspace(){}
function productActionMessage(e){return e.message;}class ApiError extends Error{}
''' + function('saveGuidedTool') + r'''
(async()=>{
 await saveGuidedTool();
 assert.equal(byId('guided-verifier-confirmation').hidden,true);
 assert.equal(byId('guided-recovery-reasons').textContent,'No saved file-identity issue detected for this confirmed configuration.');
 assert.match(byId('guided-tool-state').textContent,/Tool configuration saved/);
 assert.match(byId('guided-saved-status').textContent,/Current configuration saved/);
 assert.equal(state.pending.size,0);
 process.stdout.write(JSON.stringify({passed:true}));
})().catch(e=>{console.error(e);process.exit(1)});
'''
    assert node(code)['passed']
