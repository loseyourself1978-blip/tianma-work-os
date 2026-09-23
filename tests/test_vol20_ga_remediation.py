from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from tests.test_self_hosting import make_source_repo, approve_pack, start_codex_run, wait_for_run
from tests.test_vol19_fresh_install_first_run import fresh_settings, create_owner_and_workspace, finish_setup, USERNAME, PASSWORD
from tests.test_vol19_guided_first_delivery import environment, CHOICE, AFTER, BEFORE, git
from tests.test_vol19_verification_truth_remediation import _result_envelope
from tests.test_vol19_result_owner_delivery import _decision_payload
from twos_runtime.app import create_app
from twos_runtime.models import Project, AuditEvent, CodexInstructionPack, ProjectWorkspaceAuthorization, TaskArtifactContract
from twos_runtime import artifact_verification


def installed(tmp_path):
    repo, runner, _unused_developer_verifier = environment(tmp_path)
    settings = replace(fresh_settings(tmp_path), codex_executable=str(runner), codex_timeout_seconds=30)
    return settings, repo


def setup(client, settings, repo):
    create_owner_and_workspace(client, settings, repo)
    finish_setup(client)


def login(client):
    assert client.post('/api/auth/login', json={'username': USERNAME, 'password': PASSWORD}).status_code == 200


def new_project(client, key='second', name='Second project'):
    response = client.post('/api/projects', json={'key': key, 'name': name})
    assert response.status_code == 200, response.text
    return response.json()['id']


def new_task(client, project):
    response = client.post('/api/tasks', json={'project_id': project, 'title': 'Exact first delivery',
        'workflow_type': 'general', 'development_task': 'Write the exact approved first_delivery.txt artifact. No other changes.',
        'implementation_scope': 'first_delivery.txt only', 'required_output': AFTER})
    assert response.status_code == 200, response.text
    return response.json()['id']


def authorize(client, project, repo):
    return client.post(f'/api/projects/{project}/workspace', json={'path': str(repo), 'confirmed': True})


def config(client, project):
    checked = client.post('/api/guided-tool-setup/check', params={'project_id': project}, json=CHOICE)
    assert checked.status_code == 200, checked.text
    value = checked.json()['configuration']
    assert value['ready']
    saved = client.post('/api/guided-tool-setup/save', params={'project_id': project}, json={'configuration_id': value['id']})
    assert saved.status_code == 200, saved.text
    return value


def contract(client, task, expected=AFTER):
    saved = client.post(f'/api/tasks/{task}/artifact-verification', json={'path': 'first_delivery.txt', 'expected_text': expected})
    assert saved.status_code == 200, saved.text
    return saved.json()['contract']


def prepare(client, task):
    response = client.post(f'/api/tasks/{task}/first-delivery/prepare')
    assert response.status_code == 200, response.text
    return response.json()


def apply_result(client, run_id):
    envelope = _result_envelope(client, {}, run_id)
    assert envelope['result']['verification_result']['verdict'] == 'PASS', envelope
    candidate = client.get(f'/api/codex-runs/{run_id}/delivery-candidate').json()['candidate']
    accepted = client.post(f'/api/codex-runs/{run_id}/delivery-review/accept', json=_decision_payload(
        envelope, candidate, confirmation='ACCEPT_RESULT_FOR_DELIVERY', note='Exact artifact checked.'))
    assert accepted.status_code == 200, accepted.text
    decision = accepted.json()['review']['advanced']['decision_digest']
    response = client.post(f'/api/codex-runs/{run_id}/apply-plans')
    assert response.status_code == 200, response.text
    plan = response.json()['plan']
    approved = client.post(f"/api/apply-plans/{plan['id']}/approve", json={
        'confirmation': 'APPROVE_APPLY_PLAN', 'expected_plan_digest': plan['advanced']['plan_digest'],
        'expected_candidate_digest': plan['advanced']['candidate_digest'],
        'expected_result_digest': plan['advanced']['result_digest'], 'expected_result_review_decision_digest': decision})
    assert approved.status_code == 200, approved.text
    url = f"/api/apply-plans/{plan['id']}/apply-sessions"
    confirmation = client.get(url).json()['apply_confirmation']
    applied = client.post(url, json={'confirmation': 'APPLY_ACCEPTED_CHANGES', **{
        k: v for k, v in confirmation.items() if k.startswith('expected_')}})
    assert applied.status_code == 200, applied.text
    row = applied.json()['session']
    verified = client.post(f"/api/apply-sessions/{row['id']}/post-apply-verifications", json={'expected_journal_digest': row['journal_digest']})
    assert verified.status_code == 200, verified.text
    assert verified.json()['verification']['status'] == 'PASSED', verified.text
    return row


def test_fresh_owner_project_authorize_prepare_run_apply_and_restart(tmp_path):
    settings, first = installed(tmp_path)
    second_parent = tmp_path / 'second'; second_parent.mkdir()
    second = make_source_repo(second_parent)
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        setup(client, settings, first)
        first_project = client.get('/api/projects').json()[0]['id']
        first_task = new_task(client, first_project)
        config(client, first_project); contract(client, first_task)
        first_pack = prepare(client, first_task)
        approve_pack(client, {}, first_task, first_pack['id'])
        project = new_project(client); task = new_task(client, project)
        assert client.post(f'/api/tasks/{task}/first-delivery/prepare').status_code == 403
        assert client.post(f'/api/tasks/{task}/codex-packs').status_code == 403
        assert client.post(f'/api/tasks/{task}/codex-runs', json={
            'confirmation':'START_CODEX_RUN','idempotency_key':'unauthorized-project-run-0001',
            'pack_id':first_pack['id'],'pack_version':first_pack['version']}).status_code == 403
        assert client.get(f'/api/tasks/{task}/run-eligibility').json()['eligible'] is False
        assert client.get(f'/api/tasks/{task}/first-delivery').json()['next_action'] == 'authorize_workspace'
        for repeated in (False, True):
            response = authorize(client, project, second)
            assert response.status_code == 200, response.text
            assert response.json()['authorized'] is True
            assert response.json()['already_authorized'] is repeated
        config(client, project)
        with client.app.state.session_factory() as session:
            assert session.get(CodexInstructionPack, first_pack['id']).status == 'approved'
        assert client.app.state.settings.source_repo == first
        assert client.get(f'/api/tasks/{task}/first-delivery').json()['next_action'] == 'configure_verification'
        saved = contract(client, task)
        assert contract(client, task)['id'] == saved['id']
        pack = prepare(client, task)
        approve_pack(client, {}, task, pack['id'])
        started = start_codex_run(client, {}, task, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()['id']
        terminal = wait_for_run(client, {}, run_id, {'completed','failed','blocked','timed_out','integrity_blocked'}, timeout=60)
        assert terminal['status'] == 'completed', terminal
        assert terminal['source_repo'] == str(second)
        apply_result(client, run_id)
        assert (second / 'first_delivery.txt').read_text() == AFTER
        assert (first / 'first_delivery.txt').read_text() == BEFORE
        assert client.app.state.settings.source_repo == first
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        login(client)
        assert client.get('/api/health').json()['schema'] == 'vol20.001'
        assert client.get(f'/api/projects/{project}/workspace').json()['authorized']
        guide = client.get(f'/api/tasks/{task}/first-delivery').json()
        assert guide['stage'] == 'Commit'  # Apply is validated; Commit remains a separate Owner gate.
        assert guide['location']['post_apply_validation'] == 'PASSED'
        assert client.get('/api/guided-tool-setup', params={'project_id': project}).json()['configuration']['confirmed']
        assert (second / 'first_delivery.txt').read_text() == AFTER
        with client.app.state.session_factory() as session:
            assert len(session.scalars(select(ProjectWorkspaceAuthorization)).all()) == 1
            assert len(session.scalars(select(TaskArtifactContract)).all()) == 2


@pytest.mark.parametrize('same_key', [False, True])
def test_parallel_project_creation_is_bounded_and_unique(tmp_path, same_key):
    settings, first = installed(tmp_path)
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        setup(client, settings, first)
        barrier = threading.Barrier(2)
        def create(index):
            barrier.wait(timeout=10)
            return client.post('/api/projects', json={'key': 'parallel' if same_key else f'parallel-{index}', 'name': 'Parallel'})
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(create, i) for i in range(2)]
            responses = [f.result(timeout=20) for f in futures]
        assert sorted(r.status_code for r in responses) == ([200,409] if same_key else [200,200])
        with client.app.state.session_factory() as session:
            assert len(session.scalars(select(Project).where(Project.name == 'Parallel')).all()) == (1 if same_key else 2)
            assert len(session.scalars(select(AuditEvent).where(AuditEvent.action == 'project_created')).all()) == (1 if same_key else 2)


def test_first_readiness_releases_write_transaction_before_provider_wait(tmp_path, monkeypatch):
    import twos_runtime.codex_connectivity as connectivity
    settings, first = installed(tmp_path)
    entered = threading.Event(); release = threading.Event()
    real = connectivity._run_exec_connectivity_probe
    def blocked_probe(*args, **kwargs):
        entered.set()
        assert release.wait(20)
        return real(*args, **kwargs)
    monkeypatch.setattr(connectivity, '_run_exec_connectivity_probe', blocked_probe)
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        setup(client, settings, first)
        with ThreadPoolExecutor(max_workers=2) as pool:
            probe = pool.submit(client.post, '/api/guided-tool-setup/check', json=CHOICE)
            try:
                assert entered.wait(10)
                create = pool.submit(client.post, '/api/projects', json={'key': 'during-readiness', 'name': 'During readiness'})
                response = create.result(timeout=4)
                assert response.status_code == 200, response.text
                assert not probe.done()
            finally:
                release.set()
            checked = probe.result(timeout=30)
            assert checked.status_code == 200, checked.text
            assert checked.json()['configuration']['ready']


@pytest.mark.parametrize('path', ['.','../outside.txt','/absolute.txt','.git/config','.env','nested/../file.txt'])
def test_builtin_contract_rejects_escape_and_private_paths(path):
    with pytest.raises(ValueError): artifact_verification.specification(path, 'not executable\n')


def test_ui_release_and_normal_product_entrypoints():
    root = Path(__file__).resolve().parents[1]
    html = (root/'static_cockpit/vol12_static_mvp/twos_command_center.html').read_text()
    js = (root/'static_cockpit/vol12_static_mvp/twos_command_center.js').read_text()
    assert '<title>TWOS 1.0.0</title>' in html
    assert 'Vol.17' not in html
    for identifier in ['create-project','authorize-project-workspace','artifact-verification-save']:
        assert f'id="{identifier}"' in html
        assert f'byId("{identifier}").addEventListener' in js
    assert 'guidedProjectQuery()' in js


@pytest.mark.parametrize('boundary', ['gitfile', 'commondir'])
def test_project_scope_rejects_overlap_and_changed_git_boundary(tmp_path, boundary):
    import shutil
    settings, first = installed(tmp_path)
    parent = tmp_path/'other'; parent.mkdir()
    second = make_source_repo(parent)
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        setup(client, settings, first)
        project = new_project(client)
        assert authorize(client, project, first).status_code == 409
        assert authorize(client, project, second).status_code == 200
        task = new_task(client, project)
        # Preserve the authorized root inode while replacing only disposable
        # fixture Git metadata with a real linked-worktree boundary.
        linked = tmp_path/'linked'
        git(first, 'worktree', 'add', '--detach', str(linked), 'HEAD')
        original = second/'.git'
        if boundary == 'gitfile':
            original.rename(second/'.original-git')
            shutil.copyfile(linked/'.git', second/'.git')
        else:
            (original/'commondir').write_text(str(first/'.git')+'\n')
        response = client.post(f'/api/tasks/{task}/first-delivery/prepare')
        assert response.status_code == 403, response.text
        assert 'PROJECT_SHARED_GIT_UNSUPPORTED' in response.text
        assert client.get(f'/api/projects/{project}/workspace').json()['authorized'] is False


@pytest.mark.parametrize('damage', ['wrong_text','extra','ignored_extra','symlink','hardlink','staged','source_dirty'])
def test_shipped_verifier_rejects_scope_and_content_violations(tmp_path, damage):
    import os
    from twos_runtime.builtin_verifier import verify
    source = make_source_repo(tmp_path)
    (source/'.gitignore').write_text('extra/\n')
    git(source, 'add', '.gitignore'); git(source, 'commit', '-m', 'fixture ignore')
    commit = git(source, 'rev-parse', 'HEAD')
    work = tmp_path/'verification-work'
    git(source, 'worktree', 'add', '--detach', str(work), commit)
    target = work/'first_delivery.txt'; target.write_text(AFTER)
    spec = artifact_verification.specification('first_delivery.txt', AFTER)
    assert verify(spec, source, commit, work)['verdict'] == 'pass'
    if damage == 'wrong_text': target.write_text('wrong\n')
    elif damage in {'extra','ignored_extra'}:
        extra = work/('extra/unexpected.txt' if damage == 'ignored_extra' else 'unexpected.txt')
        extra.parent.mkdir(exist_ok=True); extra.write_text('unexpected')
    elif damage in {'symlink','hardlink'}:
        saved = tmp_path/'external-content'; saved.write_text(AFTER)
        target.unlink()
        if damage == 'symlink': target.symlink_to(saved)
        else: os.link(saved, target)
    elif damage == 'staged': git(work, 'add', 'first_delivery.txt')
    elif damage == 'source_dirty': (source/'first_delivery.txt').write_text('Owner edit\n')
    assert verify(spec, source, commit, work)['verdict'] == 'fail'


def test_generate_pack_seals_builtin_contract_and_changes_invalidate_approval(tmp_path):
    from twos_runtime.guided_delivery import pack_configuration_error
    settings, first = installed(tmp_path)
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        setup(client, settings, first)
        project = client.get('/api/projects').json()[0]['id']
        task = new_task(client, project); config(client, project)
        assert client.post(f'/api/tasks/{task}/codex-packs').status_code == 409
        contract(client, task)
        pack = client.post(f'/api/tasks/{task}/codex-packs')
        assert pack.status_code == 200, pack.text
        approve_pack(client, {}, task, pack.json()['id'])
        with client.app.state.session_factory() as session:
            row = session.get(CodexInstructionPack, pack.json()['id'])
            metadata = json.loads(row.generation_metadata)
            assert metadata['guided_delivery']['artifact_contract']['specification']['expected_text'] == AFTER
            row.generation_metadata = '{}'
            assert pack_configuration_error(session, row, client.app.state.settings)
        contract(client, task, 'Updated expected content\n')
        with client.app.state.session_factory() as session:
            assert session.get(CodexInstructionPack, pack.json()['id']).status == 'invalidated'


def test_two_projects_run_with_independent_worker_contexts(tmp_path):
    settings, first = installed(tmp_path)
    parent = tmp_path/'other'; parent.mkdir(); second = make_source_repo(parent)
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        setup(client, settings, first)
        p1 = client.get('/api/projects').json()[0]['id']; p2 = new_project(client)
        assert authorize(client, p2, second).status_code == 200
        prepared = []
        for project in (p1,p2):
            task = new_task(client, project); config(client, project); contract(client, task)
            pack = prepare(client, task); approve_pack(client, {}, task, pack['id'])
            prepared.append((task,pack))
        runs = []
        for task,pack in prepared:
            response = start_codex_run(client, {}, task, pack)
            assert response.status_code == 200, response.text
            runs.append(response.json()['id'])
        for run_id,source in zip(runs,(first,second)):
            run = wait_for_run(client, {}, run_id, {'completed','failed','blocked','timed_out','integrity_blocked'}, timeout=60)
            assert run['status'] == 'completed', run
            assert run['source_repo'] == str(source)
            assert _result_envelope(client, {}, run_id)['result']['verification_result']['verdict'] == 'PASS'
        assert client.app.state.settings.source_repo == first
        assert (first/'first_delivery.txt').read_text() == BEFORE
        assert not (second/'first_delivery.txt').exists()


def test_restore_keeps_second_project_result_but_requires_reauthorization(tmp_path):
    settings, first = installed(tmp_path)
    parent = tmp_path/'other'; parent.mkdir(); second = make_source_repo(parent)
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        setup(client, settings, first)
        project = new_project(client); assert authorize(client, project, second).status_code == 200
        task = new_task(client, project); config(client, project); contract(client, task)
        pack = prepare(client, task); approve_pack(client, {}, task, pack['id'])
        response = start_codex_run(client, {}, task, pack); assert response.status_code == 200, response.text
        run_id = response.json()['id']
        assert wait_for_run(client, {}, run_id, {'completed','failed','blocked','timed_out'}, timeout=60)['status'] == 'completed'
        before = _result_envelope(client, {}, run_id)['result']
        created = client.post('/api/maintenance/backups', json={'confirmation':'CREATE_BACKUP'})
        assert created.status_code == 200, created.text
        plan = client.post('/api/maintenance/restore-plan', json={'backup':created.json()['backup']}).json()
        assert client.post('/api/maintenance/approve-plan', json={'plan_id':plan['plan_id'],'confirmation':'APPROVE_MAINTENANCE_PLAN'}).status_code == 200
        restored = client.post('/api/maintenance/confirm', json={'plan_id':plan['plan_id'],'confirmation':'RESTORE_TWOS'})
        assert restored.status_code == 200, restored.text
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        login(client)
        response = client.post('/api/maintenance/workspace', json={'path':str(first),'confirmation':'REAUTHORIZE_WORKSPACE'})
        assert response.status_code == 200, response.text
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        login(client)
        assert client.get(f'/api/projects/{project}/workspace').json()['authorized'] is False
        assert client.get(f'/api/codex-runs/{run_id}').status_code == 200
        assert _result_envelope(client, {}, run_id)['result'] == before
        assert client.post(f'/api/tasks/{task}/first-delivery/prepare').status_code == 403
        assert client.get(f'/api/codex-runs/{run_id}/delivery').status_code == 409
        response = authorize(client, project, second)
        assert response.status_code == 200, response.text
        assert response.json()['already_authorized'] is True
        assert client.get(f'/api/projects/{project}/workspace').json()['authorized'] is True


def test_workspace_card_tool_setup_binds_selected_project_not_selected_task():
    import re
    import subprocess
    source = (Path(__file__).resolve().parents[1]/'static_cockpit/vol12_static_mvp/twos_command_center.js').read_text()
    def function(name):
        return re.search(r'^  (?:async )?function ' + name + r'\(.*?(?=^  (?:async )?function |\Z)', source, re.M|re.S)[0]
    listener = re.search(r'byId\("project-tool-setup"\)\.addEventListener\("click", (function \(\) \{.*?\})\);', source)[1]
    harness = '''
const assert = require('assert/strict');
const state = {};
const nodes = {};
function byId(id) { return nodes[id] ||= {value:'',showModal(){this.open=true;}}; }
function selectedTask(){return {id:1,project_id:11};}
function productActionMessage(e){return e.message;}
let calls=[];
async function api(path){calls.push(path);throw new Error('stop after recording passive request');}
''' + function('guidedProjectQuery') + function('openGuidedToolSetup') + '''
(async()=>{
  byId('workspace-project').value='22';
  const click = LISTENER;
  click(); await Promise.resolve();
  assert.equal(state.guidedToolProjectId,'22');
  assert.equal(calls[0],'/api/guided-tool-setup?project_id=22');
  byId('workspace-project').value='33';
  assert.equal(guidedProjectQuery(),'?project_id=22');
  await openGuidedToolSetup();
  assert.equal(calls[1],'/api/guided-tool-setup?project_id=11');
})().catch(e=>{console.error(e);process.exit(1);});
'''.replace('LISTENER',listener)
    result = subprocess.run(['node','-e',harness],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
