from dataclasses import replace
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from tests.test_vol19_fresh_install_first_run import fresh_settings, create_owner_and_workspace, finish_setup, USERNAME, PASSWORD
from twos_runtime.app import create_app
from twos_runtime.first_run import FirstRunError
from twos_runtime.models import AuditEvent, AuthorizedWorkspace, Task, Project
from twos_runtime import workspace_recovery as recovery


def fixture(tmp_path):
    settings = fresh_settings(tmp_path/'installation')
    workspace = tmp_path/'workspace'
    app = create_app(settings, start_scheduler=False)
    with TestClient(app) as client:
        create_owner_and_workspace(client, settings, workspace)
        finish_setup(client)
        with app.state.session_factory() as session:
            row = session.scalar(select(AuthorizedWorkspace))
            session.add(Task(project_id=row.project_id, owner_user_id=row.owner_user_id, title='Preserved synthetic task', workflow_type='general'))
            # Simulate the observed old mount device, without changing the directory.
            row.device_id -= 3
            row.identity_digest = hashlib.sha256(f'{row.canonical_path}\0{row.device_id}\0{row.inode}'.encode()).hexdigest()
            session.commit()
    app.state.engine.dispose()
    return settings, workspace


def login(client):
    response = client.post('/api/auth/login', json={'username':USERNAME, 'password':PASSWORD})
    assert response.status_code == 200, response.text


def test_legacy_mount_change_reproduces_then_explicit_recovery_restarts(tmp_path, monkeypatch):
    settings, workspace = fixture(tmp_path)
    with pytest.raises(FirstRunError, match='workspace identity changed') as raised:
        create_app(settings, start_scheduler=False)
    assert raised.value.code == 'WORKSPACE_IDENTITY_CHANGED'
    monkeypatch.setattr(recovery, 'volume_identity', lambda path: '11111111-1111-1111-1111-111111111111')
    original = {p.name:p.read_bytes() for p in workspace.iterdir() if p.is_file()}
    app = recovery.recovery_app(settings)
    with TestClient(app, headers={'Origin':'http://testserver'}) as client:
        assert client.get('/api/health').json()['status'] == 'workspace_review_required'
        assert client.get('/api/startup-recovery/review').status_code == 401
        login(client)
        value = client.get('/api/startup-recovery/review').json()
        assert value['history'][0]['task'] == 'Preserved synthetic task'
        review = value['review']; assert review['can_confirm']
        with app.state.session_factory() as session:
            assert recovery.latest(session) is None
        assert client.post('/api/tasks/1/codex-runs', json={}).status_code == 404
        body = {'confirmation':'CONFIRM_CURRENT_WORKSPACE', 'review_digest':review['review_digest']}
        assert client.post('/api/startup-recovery/confirm', json=body).json()['status'] == 'CONFIRMED'
        assert client.post('/api/startup-recovery/confirm', json=body).json()['status'] == 'ALREADY_CONFIRMED'
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        login(client)
        assert client.get('/api/setup/status').json()['state'] == 'ready'
        assert client.get('/api/tasks').json()[0]['title'] == 'Preserved synthetic task'
    assert {p.name:p.read_bytes() for p in workspace.iterdir() if p.is_file()} == original


@pytest.mark.parametrize('failure', ['csrf','unconfirmed','stale','inode','lock'])
def test_recovery_rejects_unsafe_or_changed_confirmation(tmp_path, failure):
    settings, workspace = fixture(tmp_path)
    app = recovery.recovery_app(settings)
    with TestClient(app, headers={'Origin':'http://testserver'}) as client:
        login(client)
        value = client.get('/api/startup-recovery/review').json()['review']
        body={'confirmation':'CONFIRM_CURRENT_WORKSPACE', 'review_digest':value['review_digest']}
        if failure=='unconfirmed': body['confirmation']=''
        if failure=='stale': body['review_digest']='0'*64
        if failure=='inode':
            workspace.rename(workspace.with_name('original-preserved'))
            workspace.mkdir(mode=0o700)
        from twos_runtime.maintenance import open_lock, database_path
        import os
        fd = open_lock(database_path(settings.database_url), exclusive=True) if failure=='lock' else None
        try:
            response=client.post('/api/startup-recovery/confirm',json=body,
                headers={'Origin':'https://foreign.invalid'} if failure=='csrf' else {})
            assert response.status_code in (400,403,409),response.text
        finally:
            if fd is not None: os.close(fd)
        with app.state.session_factory() as session:
            assert recovery.latest(session) is None


def test_confirmed_volume_does_not_relax_directory_or_volume_boundary(tmp_path, monkeypatch):
    settings, workspace = fixture(tmp_path)
    monkeypatch.setattr(recovery, 'volume_identity', lambda path:'VOLUME-A')
    app=recovery.recovery_app(settings)
    with TestClient(app,headers={'Origin':'http://testserver'}) as client:
        login(client)
        review=client.get('/api/startup-recovery/review').json()['review']
        assert client.post('/api/startup-recovery/confirm',json={'confirmation':'CONFIRM_CURRENT_WORKSPACE','review_digest':review['review_digest']}).status_code==200
        with app.state.session_factory() as session:
            row=session.scalar(select(AuthorizedWorkspace))
            metadata=SimpleNamespace(st_dev=row.device_id+5,st_ino=row.inode)
            identity=hashlib.sha256(f'{workspace}\0{metadata.st_dev}\0{metadata.st_ino}'.encode()).hexdigest()
            assert recovery.binding_matches(session,row,workspace,metadata,identity)
            metadata.st_ino+=1
            assert not recovery.binding_matches(session,row,workspace,metadata,identity)
            metadata.st_ino-=1
            monkeypatch.setattr(recovery,'volume_identity',lambda path:'VOLUME-B')
            assert not recovery.binding_matches(session,row,workspace,metadata,identity)


def test_diagnostics_exclude_exception_message_locals_and_private_paths():
    from twos_runtime.desktop import failure_detail
    try:
        raise ValueError('Bearer secret-sentinel /Users/private/account')
    except ValueError as exc:
        detail=failure_detail(exc,'application_initialization')
    encoded=json.dumps(detail)
    assert 'secret-sentinel' not in encoded and '/Users/' not in encoded
    assert detail['exception_type']=='ValueError'


def test_old_approval_guard_and_recovery_epoch(tmp_path):
    settings, workspace=fixture(tmp_path)
    app=recovery.recovery_app(settings)
    with TestClient(app,headers={'Origin':'http://testserver'}) as client:
        login(client)
        review=client.get('/api/startup-recovery/review').json()['review']
        assert client.post('/api/startup-recovery/confirm',json={'confirmation':'CONFIRM_CURRENT_WORKSPACE','review_digest':review['review_digest']}).status_code==200
        from twos_runtime.maintenance import recovery_epoch
        assert len(recovery_epoch(settings))==64
        with app.state.session_factory() as session:
            owner=session.scalar(select(AuthorizedWorkspace)).owner_user_id
            with pytest.raises(FirstRunError,match='read-only'):
                recovery.guard_mutation(session,owner,'POST','/api/tasks/1/codex-runs',pack_id=0)
            recovery.guard_mutation(session,owner,'GET','/api/codex-runs/1')


def test_confirmed_volume_must_match_even_if_device_number_is_reused(tmp_path, monkeypatch):
    settings, workspace = fixture(tmp_path)
    monkeypatch.setattr(recovery, 'volume_identity', lambda path: 'VOLUME-A')
    app = recovery.recovery_app(settings)
    with TestClient(app, headers={'Origin': 'http://testserver'}) as client:
        login(client)
        value = client.get('/api/startup-recovery/review').json()['review']
        assert client.post('/api/startup-recovery/confirm', json={
            'confirmation': 'CONFIRM_CURRENT_WORKSPACE', 'review_digest': value['review_digest']}).status_code == 200
        monkeypatch.setattr(recovery, 'volume_identity', lambda path: 'VOLUME-B')
        with app.state.session_factory() as session:
            row = session.scalar(select(AuthorizedWorkspace))
            assert not recovery.binding_matches(session, row, workspace, workspace.stat(), row.identity_digest)


def test_missing_optional_tool_does_not_block_recovered_app_history(tmp_path, monkeypatch):
    settings, workspace = fixture(tmp_path)
    settings = replace(settings, codex_executable=str(tmp_path/'absent-codex'),
        local_verification_command=(str(tmp_path/'absent-verifier'),))
    monkeypatch.setattr(recovery, 'volume_identity', lambda path: 'VOLUME-A')
    app = recovery.recovery_app(settings)
    with TestClient(app, headers={'Origin': 'http://testserver'}) as client:
        login(client)
        value = client.get('/api/startup-recovery/review').json()['review']
        assert client.post('/api/startup-recovery/confirm', json={
            'confirmation': 'CONFIRM_CURRENT_WORKSPACE', 'review_digest': value['review_digest']}).status_code == 200
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        login(client)
        assert client.get('/api/tasks').json()[0]['title'] == 'Preserved synthetic task'
        setup = client.get('/api/guided-tool-setup').json()
        assert setup['discovery']['status'] == 'Needs Setup'
        assert setup['provider_request_performed'] is False


def test_archived_delivered_projection_keeps_confirmation_contract_without_transport(tmp_path, monkeypatch):
    from tests import test_vol19_owner_commit_push_delivery as delivery
    from twos_runtime.models import PushExecution
    from tests.test_vol19_guided_acceptance_corrections import function, node
    from twos_runtime import push_delivery
    import os
    for key in tuple(os.environ):
        if key.startswith('GIT_'):
            monkeypatch.delenv(key)
    with delivery._canonical_applied_delivery(tmp_path/'archived') as fixture:
        _, _, commit = delivery._commit_delivery(fixture)
        response = fixture.client.post(f"/api/local-commits/{commit['id']}/push-plans", json={})
        assert response.status_code == 200, response.text
        plan = response.json()['push_plan']
        response = fixture.client.post(f"/api/push-plans/{plan['id']}/approvals", json={
            'confirmation':'APPROVE_PUSH_PLAN','expected_plan_digest':plan['advanced']['plan_digest'],
            'expected_plan_version':plan['version']})
        assert response.status_code == 200, response.text
        approval = response.json()['push_approval']
        response = fixture.client.post(f"/api/push-plans/{plan['id']}/push-attempts", json={
            'confirmation':'PUSH_TO_ORIGIN_MAIN','expected_plan_digest':plan['advanced']['plan_digest'],
            'expected_approval_digest':approval['advanced']['approval_digest']})
        assert response.status_code == 200, response.text
        monkeypatch.setattr(recovery, 'latest', lambda *a, **k: {'historical_cutoffs': {'codex_runs':fixture.run_id}})
        def no_transport(*args, **kwargs):
            raise AssertionError('Archived receipt must not perform live reconciliation')
        monkeypatch.setattr(push_delivery, '_reconciliation_locked', no_transport)
        monkeypatch.setattr(push_delivery, '_safe_preflight_observation', no_transport)
        for path in (f'/api/codex-runs/{fixture.run_id}/delivery', f"/api/local-commits/{commit['id']}/push-delivery"):
            response = fixture.client.get(path)
            assert response.status_code == 200, response.text
            view = response.json().get('push_delivery', response.json())
            assert view['confirmation']['state'] == 'succeeded'
            assert view['confirmation']['can_confirm'] is False
            assert view['delivery_result']['status_label'] == 'DELIVERED'
            assert view['delivery_result']['verified_remote_sha'] == commit['commit_oid']
            assert view['actions']['can_confirm_push'] is False
        harness = '''
const state={pending:new Set(),ownerPushConfirmationState:{}};
function objectRecord(v){return v||{};}
function ownerPushConfirmationRequestInFlight(){return false;}
function ownerPushConfirmationUncertaintyActive(){return false;}
function ownerPushReviewAttempt(){return {};}
function ownerPushConfirmationProjectionRelevant(){return true;}
function ownerDeliveryRecordId(v){return v?.id;}
const parts=PARTS;
'''.replace('PARTS',json.dumps({'pushConfirmation':view['confirmation'],'receipt':view['delivery_result'],'pushActions':view['actions']}))
        result = node(harness + function('canonicalPushState') + '\nprocess.stdout.write(JSON.stringify(canonicalPushState(parts)));')
        assert result == 'DELIVERED'
        with fixture.factory() as session:
            row = session.scalar(select(PushExecution))
            assert row.command_attempt_count == 1
        assert delivery._bare_ref(fixture.origin) == commit['commit_oid']
