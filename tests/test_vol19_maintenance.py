from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_vol19_fresh_install_first_run import fresh_settings, create_owner_and_workspace, finish_setup, USERNAME, PASSWORD
from twos_runtime.app import create_app
from twos_runtime.maintenance import Maintenance, MaintenanceError, digest, file_hash, inspect_database, logical_digest, readonly, safe_state, snapshot
from twos_runtime.models import User, SessionToken, utc_now
from twos_runtime.security import hash_password, hash_token


def task(client, title):
    project = client.get('/api/projects').json()[0]['id']
    response = client.post('/api/tasks', json={'project_id': project, 'title': title, 'workflow_type': 'general'})
    assert response.status_code == 200, response.text
    return response.json()['id']


def login(client):
    response = client.post('/api/auth/login', json={'username': USERNAME, 'password': PASSWORD})
    assert response.status_code == 200, response.text


@pytest.fixture
def installation(tmp_path):
    settings = fresh_settings(tmp_path)
    workspace = tmp_path / 'workspace'
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        create_owner_and_workspace(client, settings, workspace)
        finish_setup(client)
        task(client, '19.3 baseline Task')
    return settings, workspace


def backup(service):
    return Path(service.create_backup()['backup'])


def approved_restore(service, bundle):
    plan = service.restore_plan(str(bundle), 1)
    service.approve_plan(plan['plan_id'], 1)
    return plan


def mutate_title(service):
    with closing(sqlite3.connect(service.db)) as connection:
        connection.execute("UPDATE tasks SET title='POST BACKUP MUTATION'")
        connection.commit()


def assert_baseline(service):
    with readonly(service.db) as connection:
        assert connection.execute('SELECT title FROM tasks').fetchone()[0] == '19.3 baseline Task'


def test_explicit_backup_restore_preserves_state_and_requires_reauthorization(installation):
    settings, workspace = installation
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        login(client)
        status = client.get('/api/maintenance/status').json()
        assert status['backup_ready'] is True, status
        service = client.app.state.maintenance
        assert not service.backups.exists()
        assert client.post('/api/maintenance/backups', json={}).status_code == 400
        created = client.post('/api/maintenance/backups', json={'confirmation': 'CREATE_BACKUP'})
        assert created.status_code == 200, created.text
        bundle = created.json()['backup']
        inspected = client.post('/api/maintenance/inspect', json={'backup': bundle}).json()
        assert inspected['integrity_status'] == 'VERIFIED'
        with readonly(Path(bundle) / 'database.sqlite3') as connection:
            assert connection.execute('SELECT COUNT(*) FROM session_tokens').fetchone()[0] == 0
        task(client, 'POST BACKUP MUTATION')
        plan = client.post('/api/maintenance/restore-plan', json={'backup': bundle}).json()
        confirmed = {'plan_id': plan['plan_id'], 'confirmation': 'RESTORE_TWOS'}
        assert client.post('/api/maintenance/confirm', json=confirmed).status_code == 403
        assert client.post('/api/maintenance/approve-plan', json={'plan_id': plan['plan_id'], 'confirmation': 'APPROVE_MAINTENANCE_PLAN'}).status_code == 200
        restored = client.post('/api/maintenance/confirm', json=confirmed)
        assert restored.status_code == 200, restored.text
        assert restored.json()['state'] == 'RESTORE_COMPLETE'
        assert client.get('/api/maintenance/status').status_code == 401
        login(client)
        data = client.get('/api/maintenance/data').json()
        assert [t['title'] for t in data['tasks']] == ['19.3 baseline Task']
        assert client.get('/api/tasks').status_code == 428
        assert client.get('/api/maintenance/status').json()['authority']['workspace_status'] == 'REAUTHORIZATION_REQUIRED'
        for table in ('codex_runs', 'apply_sessions', 'local_commit_executions', 'push_executions'):
            assert data['counts'][table] == 0
    with TestClient(create_app(settings, start_scheduler=False)) as restarted:
        login(restarted)
        assert restarted.get('/api/maintenance/status').json()['standalone'] is True
        assert restarted.post('/api/maintenance/workspace', json={'path': str(workspace), 'confirmation': 'REAUTHORIZE_WORKSPACE'}).status_code == 200
    with TestClient(create_app(settings, start_scheduler=False)) as restarted:
        login(restarted)
        assert [t['title'] for t in restarted.get('/api/tasks').json()] == ['19.3 baseline Task']
        assert restarted.get('/api/maintenance/status').json()['authority']['workspace_status'] == 'AUTHORIZED'


@pytest.mark.parametrize('boundary', ['backup_before_snapshot', 'backup_during_copy', 'backup_before_seal', 'backup_before_rename'])
def test_backup_faults_never_present_incomplete_as_valid(installation, boundary):
    settings, _ = installation
    def fault(at):
        if at == boundary:
            raise RuntimeError('injected local failure')
    service = Maintenance(settings, fault=fault)
    before = logical_digest(service.db)
    with pytest.raises(RuntimeError):
        service.create_backup()
    assert logical_digest(service.db) == before
    assert service.journal()['state'] == 'BACKUP_FAILED'
    assert list(service.backups.iterdir()) == []
    Maintenance(settings).reconcile()
    assert_baseline(service)


@pytest.mark.parametrize('boundary', ['restore_before_snapshot', 'restore_before_stage', 'restore_after_staged_verification', 'restore_before_activation', 'restore_after_activation', 'restore_post_verify'])
def test_restore_fault_preserves_prior_healthy_state_before_teardown(installation, boundary):
    settings, _ = installation
    service = Maintenance(settings)
    bundle = backup(service)
    mutate_title(service)
    before = logical_digest(service.db)
    plan = approved_restore(service, bundle)
    def fault(at):
        if at == boundary:
            raise RuntimeError('injected restore failure')
    service.fault = fault
    with pytest.raises(RuntimeError):
        service.execute_plan(plan['plan_id'], 1, 'RESTORE_TWOS')
    assert service.journal()['state'] == 'RESTORE_FAILED'
    assert service.journal()['active_healthy'] is True
    assert logical_digest(service.db) == before
    Maintenance(settings).reconcile()
    assert logical_digest(service.db) == before


@pytest.mark.parametrize('damage', ['manifest', 'hash', 'missing_database', 'future_format', 'future_schema', 'unsafe_member', 'symlink'])
def test_corrupt_restore_is_rejected_without_activation(installation, tmp_path, damage):
    settings, _ = installation
    service = Maintenance(settings)
    bundle = backup(service)
    corrupt = tmp_path / 'corrupt.twos-backup'
    shutil.copytree(bundle, corrupt)
    manifest_path = corrupt / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if damage == 'manifest':
        manifest_path.write_text('{not JSON')
    elif damage == 'hash':
        with (corrupt / 'database.sqlite3').open('ab') as stream:
            stream.write(b'corrupted')
    elif damage == 'missing_database':
        (corrupt / 'database.sqlite3').unlink()
    elif damage == 'symlink':
        (corrupt / 'database.sqlite3').unlink()
        (corrupt / 'database.sqlite3').symlink_to(bundle / 'database.sqlite3')
    else:
        if damage == 'future_format': manifest['format'] = 'TWOS_BACKUP_V99'
        if damage == 'future_schema': manifest['schema_version'] = 'vol99.001'
        if damage == 'unsafe_member': manifest['files']['../../escape'] = {'sha256': '0'*64, 'size': 0}
        manifest['integrity'] = digest({k: v for k, v in manifest.items() if k != 'integrity'})
        manifest_path.write_text(json.dumps(manifest))
    before = file_hash(service.db)
    with pytest.raises(MaintenanceError):
        service.restore_plan(str(corrupt), 1)
    assert file_hash(service.db) == before
    assert service.journal()['state'] == 'BACKUP_COMPLETE'


@pytest.mark.parametrize('boundary,activated', [('restore_after_staged_verification', False), ('restore_before_activation', False), ('restore_after_activation', True), ('restore_post_verify', True)])
def test_process_interruption_recovers_on_restart_without_external_replay(installation, boundary, activated):
    settings, _ = installation
    service = Maintenance(settings)
    bundle = backup(service)
    mutate_title(service)
    before = logical_digest(service.db)
    plan = approved_restore(service, bundle)
    code = '''
import os, sys
from twos_runtime.config import Settings
from twos_runtime.maintenance import Maintenance
service = Maintenance(Settings(database_url=sys.argv[1]), fault=lambda at: os._exit(73) if at == sys.argv[2] else None)
service.execute_plan(sys.argv[3], 1, 'RESTORE_TWOS')
'''
    result = subprocess.run([sys.executable, '-c', code, settings.database_url, boundary, plan['plan_id']], capture_output=True)
    assert result.returncode == 73, result.stderr.decode()
    recovered = Maintenance(settings)
    recovered.reconcile()
    assert recovered.journal()['state'] == 'RECOVERY_COMPLETE'
    assert recovered.journal()['active_healthy'] is True
    if activated:
        assert_baseline(recovered)
        assert recovered.authority()['workspace_status'] == 'REAUTHORIZATION_REQUIRED'
    else:
        assert logical_digest(service.db) == before
    assert not (recovered.root / 'staged.sqlite3').exists()
    assert inspect_database(service.db)['counts']['codex_runs'] == 0


def test_owner_only_maintenance_and_no_automatic_requests(installation):
    settings, _ = installation
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        assert client.get('/api/maintenance/status').status_code == 401
        assert client.post('/api/maintenance/backups', json={'confirmation':'CREATE_BACKUP'}).status_code == 401
        login(client)
        assert client.get('/maintenance').status_code == 200
        assert client.get('/api/maintenance/status').json()['provider_request_performed'] is False
        assert not client.app.state.maintenance.root.exists()
        pw_hash, salt = hash_password('isolation-fixture-password')
        token = 'isolated-maintenance-second-account-token'
        with client.app.state.session_factory() as session:
            user = User(username='other', password_hash=pw_hash, password_salt=salt)
            session.add(user); session.flush()
            session.add(SessionToken(user_id=user.id, token_hash=hash_token(token), expires_at=utc_now()+timedelta(hours=1)))
            session.commit()
        client.headers['Authorization'] = 'Bearer ' + token
        for route, payload in [('backups', {'confirmation':'CREATE_BACKUP'}), ('restore-plan', {'backup':'/invalid'}), ('migration-plan', {}), ('approve-plan', {'confirmation':'APPROVE_MAINTENANCE_PLAN'}), ('confirm', {}), ('workspace', {'confirmation':'REAUTHORIZE_WORKSPACE'})]:
            assert client.post('/api/maintenance/'+route, json=payload).status_code == 403


def test_paths_and_backup_allowlist_exclude_credentials_and_workspace(installation, tmp_path):
    settings, workspace = installation
    service = Maintenance(settings)
    (workspace/'never-copy.txt').write_text('unrelated source secret')
    (settings.data_root/'auth.json').write_text('provider credential must never be copied')
    (settings.data_root/'cookie.txt').write_text('browser cookie must never be copied')
    bundle = backup(service)
    files = {str(p.relative_to(bundle)) for p in bundle.rglob('*') if p.is_file()}
    assert files == {'manifest.json', 'database.sqlite3', 'logical-installation.json'}
    assert bundle.stat().st_mode & 0o077 == 0
    assert all(p.stat().st_mode & 0o077 == 0 for p in bundle.iterdir())
    contents = b''.join(p.read_bytes() for p in bundle.iterdir())
    for secret in (b'unrelated source secret', b'provider credential must never be copied', b'browser cookie must never be copied', PASSWORD.encode()):
        assert secret not in contents
    with pytest.raises(MaintenanceError, match='traversal'):
        service.inspect_backup(str(bundle.parent/'..'/bundle.name))
    link = tmp_path/'linked.twos-backup'; link.symlink_to(bundle)
    with pytest.raises(MaintenanceError, match='Symbolic'):
        service.inspect_backup(str(link))
    victim = tmp_path/'victim'; victim.write_text('untouched')
    linked = tmp_path/'hardlink'; os.link(victim, linked)
    with pytest.raises(MaintenanceError): snapshot(service.db, linked)
    assert victim.read_text() == 'untouched'


def test_another_runtime_connection_blocks_backup(installation):
    from twos_runtime.db import make_engine
    settings, _ = installation
    engine = make_engine(settings.database_url)
    try:
        with engine.connect():
            with pytest.raises(MaintenanceError, match='Another connection'):
                backup(Maintenance(settings))
    finally:
        engine.dispose()
    assert backup(Maintenance(settings)).is_dir()


def test_material_plan_drift_and_wrong_confirmation_do_not_activate(installation):
    settings, _ = installation
    service = Maintenance(settings)
    plan = approved_restore(service, backup(service))
    with pytest.raises(MaintenanceError):
        service.execute_plan(plan['plan_id'], 1, 'WRONG')
    mutate_title(service)
    with pytest.raises(MaintenanceError, match='changed after review'):
        service.execute_plan(plan['plan_id'], 1, 'RESTORE_TWOS')
    assert service.journal()['state'] == 'BACKUP_COMPLETE'


@pytest.mark.parametrize('table,column,state',[
    ('codex_runs','status','running'),('codex_execution_attempts','attempt_state','VERIFICATION_ELIGIBLE'),
    ('codex_run_monitors','monitor_state','RESULT_PENDING'),('task_runs','status','running'),
    ('apply_sessions','state','APPLYING'),('apply_sessions','state','REVERTING'),
    ('apply_sessions','state','APPLY_FAILED_PARTIAL'),('stage_executions','state','STAGING'),
    ('stage_executions','state','INTEGRITY_BLOCKED'),('local_commit_executions','state','COMMITTING'),
    ('push_executions','state','PUSHING'),('push_executions','state','RECONCILIATION_BLOCKED')])
def test_each_mutable_operation_has_an_exact_backup_blocker(tmp_path,table,column,state):
    # A unit fixture for the read-only admission predicate, not a historical
    # schema or a fabricated completed delivery acceptance fixture.
    db=tmp_path/'admission.sqlite3'
    with closing(sqlite3.connect(db)) as connection:
        connection.execute(f'CREATE TABLE {table}(id INTEGER, {column} TEXT)')
        connection.execute(f'INSERT INTO {table} VALUES(1,?)',(state,))
        connection.commit()
    with pytest.raises(MaintenanceError, match=state): safe_state(db)


def test_stored_provider_credentials_block_backup_without_exposure(installation):
    settings,_=installation
    service=Maintenance(settings)
    secret='sk-fixture-credential-that-must-never-be-backed-up'
    with closing(sqlite3.connect(service.db)) as connection:
        connection.execute('UPDATE tasks SET objective=?',(secret,));connection.commit()
    before=logical_digest(service.db)
    with pytest.raises(MaintenanceError) as error: backup(service)
    assert error.value.code=='STORED_CREDENTIAL_BLOCKED'
    assert secret not in str(error.value)
    assert secret not in service.journal_path.read_text()
    assert not list(service.backups.iterdir())
    assert logical_digest(service.db)==before


@pytest.mark.parametrize('alteration',['missing','corrupt','empty'])
def test_recovery_authority_cannot_silently_reenable_old_configuration(installation,alteration):
    from twos_runtime.maintenance import recovery_epoch
    settings,_=installation
    service=Maintenance(settings)
    plan=approved_restore(service,backup(service))
    service.execute_plan(plan['plan_id'],1,'RESTORE_TWOS')
    original_epoch=recovery_epoch(settings)
    if alteration=='missing':
        service.authority_path.unlink()
        assert recovery_epoch(settings)==original_epoch
        assert service.authority()['workspace_status']=='REAUTHORIZATION_REQUIRED'
    else:
        service.authority_path.write_text('{' if alteration=='corrupt' else '{}')
        with pytest.raises(MaintenanceError): recovery_epoch(settings)


def test_changed_workspace_never_reauthorizes_itself(installation,tmp_path):
    settings,workspace=installation
    service=Maintenance(settings)
    plan=approved_restore(service,backup(service))
    service.execute_plan(plan['plan_id'],1,'RESTORE_TWOS')
    moved=tmp_path/'old-workspace'; workspace.rename(moved)
    workspace.symlink_to(moved)
    with TestClient(create_app(settings,start_scheduler=False)) as client:
        login(client)
        assert client.get('/api/maintenance/status').json()['authority']['workspace_status']=='REAUTHORIZATION_REQUIRED'
        response=client.post('/api/maintenance/workspace',json={'path':str(workspace),'confirmation':'REAUTHORIZE_WORKSPACE'})
        assert response.status_code in {400,409}, response.text
        assert service.authority()['workspace_status']=='REAUTHORIZATION_REQUIRED'


def test_wal_restore_failure_keeps_the_actual_prior_state(installation):
    settings,_=installation
    service=Maintenance(settings)
    bundle=backup(service)
    with closing(sqlite3.connect(service.db)) as connection:
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute("UPDATE tasks SET title='healthy WAL mutation'");connection.commit()
    plan=approved_restore(service,bundle)
    before=logical_digest(service.db)
    service.fault=lambda at: (_ for _ in ()).throw(RuntimeError('injected')) if at=='restore_after_staged_verification' else None
    with pytest.raises(RuntimeError): service.execute_plan(plan['plan_id'],1,'RESTORE_TWOS')
    service.reconcile()
    assert logical_digest(service.db)==before
    assert service.journal()['active_healthy'] is True


@pytest.mark.parametrize('boundary', ['backup_before_snapshot', 'backup_during_copy', 'backup_before_seal', 'backup_before_rename'])
def test_backup_process_interruption_removes_partial_before_teardown(installation, boundary):
    settings, _ = installation
    service = Maintenance(settings)
    before = logical_digest(service.db)
    code = """import os,sys
from twos_runtime.config import Settings
from twos_runtime.maintenance import Maintenance
Maintenance(Settings(database_url=sys.argv[1]),fault=lambda at:os._exit(76) if at==sys.argv[2] else None).create_backup()
"""
    result = subprocess.run([sys.executable,'-c',code,settings.database_url,boundary],capture_output=True)
    assert result.returncode == 76, result.stderr.decode()
    service.reconcile()
    assert service.journal()['state'] == 'BACKUP_FAILED'
    assert list(service.backups.iterdir()) == []
    assert logical_digest(service.db) == before


def test_repeated_backup_inspect_and_owner_reads_release_file_handles(installation):
    settings, _ = installation
    service = Maintenance(settings)
    baseline = len(os.listdir('/dev/fd'))
    for _ in range(8):
        created = service.create_backup()
        assert service.inspect_backup(created['backup'])['integrity_status'] == 'VERIFIED'
        assert service.status()['backup_ready']
        service.reconcile()
    assert len(os.listdir('/dev/fd')) <= baseline
    assert not list(service.backups.glob('*.partial'))


def test_restore_copies_only_exact_approved_bytes_even_if_source_changes_after_inspection(installation):
    settings, _ = installation
    service = Maintenance(settings)
    bundle = backup(service)
    plan = approved_restore(service,bundle)
    before = logical_digest(service.db)
    def fault(at):
        if at == 'restore_before_stage':
            with closing(sqlite3.connect(bundle/'database.sqlite3')) as connection:
                connection.execute("UPDATE tasks SET title='SUBSTITUTED AFTER INSPECTION'")
                connection.commit()
    service.fault = fault
    with pytest.raises(MaintenanceError) as rejected:
        service.execute_plan(plan['plan_id'],1,'RESTORE_TWOS')
    assert rejected.value.code == 'BACKUP_CHANGED'
    assert logical_digest(service.db) == before
    assert service.journal()['state'] == 'RESTORE_FAILED'
    assert not list(service.root.glob('*.partial'))


def test_unresolved_recovery_blocks_normal_routes_immediately_without_restart(installation, monkeypatch):
    settings,_=installation
    with TestClient(create_app(settings,start_scheduler=False)) as client:
        login(client)
        service=client.app.state.maintenance
        monitor=client.app.state.result_intake_monitor
        starts=[]
        monkeypatch.setattr(monitor,'start',lambda:starts.append(True))
        def unresolved():
            with service.exclusive():
                service.begin('RESTORE')
                service.record('RECOVERY_REQUIRED',active_healthy=False,next_action='Restart in Maintenance.')
            raise MaintenanceError('RECOVERY_REQUIRED','Restart in Maintenance.')
        monkeypatch.setattr(service,'create_backup',unresolved)
        response=client.post('/api/maintenance/backups',json={'confirmation':'CREATE_BACKUP'})
        assert response.status_code==409,response.text
        assert client.get('/api/tasks').status_code==428
        assert client.post('/api/tasks',json={}).status_code==428
        assert starts==[]
        assert client.get('/api/maintenance/status').json()['backup_ready'] is False
        # Explicit test observation proves the fail-closed state before teardown.
        # The injected case made no active mutation or recovery point.
        client.app.state.engine.dispose()
        with service.exclusive():
            service.record('RESTORE_FAILED',active_healthy=True,next_action='Healthy installation unchanged.')


def test_unapplied_result_material_is_preserved_and_rebackup_needs_no_old_worktree(tmp_path, monkeypatch):
    from tests.test_self_hosting import make_source_repo, make_fake_codex, make_client, init_and_login
    from tests.test_vol19_verification_truth_remediation import make_local_verifier
    from tests.test_vol19_result_owner_delivery import _run_verified_result
    for key in list(os.environ):
        if key.startswith('GIT_'):
            monkeypatch.delenv(key)
    source = make_source_repo(tmp_path)
    runner = make_fake_codex(tmp_path)
    verifier = make_local_verifier(tmp_path)
    with make_client(tmp_path,source,runner,timeout=20,local_verification_command=verifier) as client:
        headers=init_and_login(client)
        run_id, terminal, result = _run_verified_result(client,headers)
        settings=client.app.state.settings
        response=client.post('/api/maintenance/backups',headers=headers,json={'confirmation':'CREATE_BACKUP'})
        assert response.status_code==200,response.text
        bundle=Path(response.json()['backup'])
        with readonly(bundle/'database.sqlite3') as connection:
            assert connection.execute('SELECT COUNT(*) FROM apply_sessions').fetchone()[0]==0
    service=Maintenance(settings)
    approved=approved_restore(service,bundle)
    service.execute_plan(approved['plan_id'],1,'RESTORE_TWOS')
    old_worktree=Path(terminal['worktree_path'])
    shutil.rmtree(old_worktree)
    rebuilt=service.create_backup()
    manifest=service.inspect_backup(rebuilt['backup'])['manifest']
    assert any(name.startswith('result-material/') for name in manifest['files'])
    assert not old_worktree.exists()
    assert service.authority()['workspace_status']=='REAUTHORIZATION_REQUIRED'


def test_pending_terminal_result_blocks_backup_until_canonical_settlement(tmp_path):
    db=tmp_path/'predicate.sqlite3'
    with closing(sqlite3.connect(db)) as connection:
        connection.executescript("CREATE TABLE codex_runs(id INTEGER,status TEXT,structured_result TEXT,finished_at TEXT); CREATE TABLE codex_run_monitors(id INTEGER,run_id INTEGER,monitor_state TEXT,terminal_at TEXT); CREATE TABLE codex_result_envelopes(id INTEGER,run_id INTEGER);")
        connection.execute("INSERT INTO codex_runs VALUES(1,'completed','terminal evidence',?)", (utc_now().isoformat(),))
        connection.execute("INSERT INTO codex_run_monitors VALUES(1,1,'RESULT_UNAVAILABLE',?)", (utc_now().isoformat(),))
        connection.commit()
    with pytest.raises(MaintenanceError) as blocked:
        safe_state(db)
    assert blocked.value.code=='RESULT_SETTLING'


def test_maintenance_read_holds_cross_process_lease_and_blocks_overlapping_backup(installation, monkeypatch):
    import threading
    settings,_=installation
    with TestClient(create_app(replace(settings,maintenance_mode=True),start_scheduler=False)) as client:
        login(client)
        service=client.app.state.maintenance
        entered=threading.Event(); release=threading.Event()
        real=service.status
        responses=[]
        def slow_status():
            entered.set()
            assert release.wait(10)
            return real()
        monkeypatch.setattr(service,'status',slow_status)
        thread=threading.Thread(target=lambda:responses.append(client.get('/api/maintenance/status')))
        thread.start()
        try:
            assert entered.wait(5)
            with pytest.raises(MaintenanceError) as locked:
                with Maintenance(settings).exclusive():
                    pass
            assert locked.value.code=='INSTALLATION_BUSY'
            response=client.post('/api/maintenance/backups',json={'confirmation':'CREATE_BACKUP'})
            assert response.status_code==409,response.text
            assert response.json()['error']['code']=='INSTALLATION_BUSY'
        finally:
            release.set();thread.join(10)
        assert not thread.is_alive()
        assert responses[0].status_code==200
        assert service.journal()['state']=='NONE'


def test_restore_invalidates_confirmed_tool_configuration_and_future_pack_without_probe(tmp_path, monkeypatch):
    from tests.test_self_hosting import make_client, init_and_login, OWNER_PASSWORD
    from tests.test_vol19_guided_first_delivery import environment, check_and_save, create_task
    for key in list(os.environ):
        if key.startswith('GIT_'):
            monkeypatch.delenv(key)
    source, runner, verifier = environment(tmp_path)
    with make_client(tmp_path,source,runner,timeout=20,local_verification_command=verifier) as client:
        init_and_login(client)
        task_id=create_task(client)
        config=check_and_save(client)
        prepared=client.post(f'/api/tasks/{task_id}/first-delivery/prepare')
        assert prepared.status_code==200,prepared.text
        settings=client.app.state.settings
        response=client.post('/api/maintenance/backups',json={'confirmation':'CREATE_BACKUP'})
        assert response.status_code==200,response.text
        bundle=Path(response.json()['backup'])
    probe_marker=runner.with_name(runner.name+'.probe-executed')
    original_marker=probe_marker.read_bytes()
    service=Maintenance(settings)
    plan=approved_restore(service,bundle)
    service.execute_plan(plan['plan_id'],1,'RESTORE_TWOS')
    with TestClient(create_app(settings,start_scheduler=False)) as client:
        assert client.post('/api/auth/login',json={'username':'owner','password':OWNER_PASSWORD}).status_code==200
        response=client.post('/api/maintenance/workspace',json={'path':str(source),'confirmation':'REAUTHORIZE_WORKSPACE'})
        assert response.status_code==200,response.text
    with make_client(tmp_path,source,runner,timeout=20,local_verification_command=verifier) as client:
        init_and_login(client)
        state=client.get('/api/guided-tool-setup').json()
        assert not state['configuration']['ready']
        response=client.post(f'/api/tasks/{task_id}/first-delivery/prepare')
        assert response.status_code in {409,428},response.text
        assert client.get('/api/maintenance/data').json()['counts']['codex_runs']==0
        assert probe_marker.read_bytes()==original_marker


@pytest.mark.parametrize('kind',['symlink','hardlink'])
def test_direct_engine_initializer_cannot_bypass_unsafe_database_path(installation,tmp_path,kind):
    from twos_runtime.db import make_engine
    settings,_=installation
    service=Maintenance(settings)
    before=file_hash(service.db)
    linked=tmp_path/'unsafe.sqlite3'
    if kind=='symlink':
        linked.symlink_to(service.db)
    else:
        os.link(service.db,linked)
    try:
        with pytest.raises(MaintenanceError) as rejected:
            make_engine('sqlite+pysqlite:///'+str(linked))
        assert rejected.value.code=='UNSAFE_PATH'
        assert file_hash(service.db)==before
    finally:
        linked.unlink()


def test_rejected_connection_admission_releases_sqlite_and_lock_handles(installation):
    from twos_runtime.db import make_engine
    settings,_=installation
    service=Maintenance(settings)
    engine=make_engine(settings.database_url)
    try:
        with service.exclusive():
            before=len(os.listdir('/dev/fd'))
            for _ in range(12):
                with pytest.raises(MaintenanceError):
                    with engine.connect():
                        pass
            assert len(os.listdir('/dev/fd'))<=before
    finally:
        engine.dispose()


def test_malicious_recovery_journal_cannot_clean_an_unrelated_directory(installation,tmp_path):
    from twos_runtime.maintenance import atomic_json
    settings,_=installation
    service=Maintenance(settings)
    service.prepare()
    unrelated=tmp_path/'unrelated.partial'
    unrelated.mkdir(); (unrelated/'keep.txt').write_text('untouched')
    atomic_json(service.journal_path,{'operation_id':str(unrelated).removesuffix('.partial'),'kind':'BACKUP','state':'BACKUP_STARTED'})
    with pytest.raises(MaintenanceError) as rejected:
        service.reconcile()
    assert rejected.value.code=='RECOVERY_JOURNAL_INVALID'
    assert (unrelated/'keep.txt').read_text()=='untouched'
    service.journal_path.unlink()
    assert_baseline(service)


@pytest.mark.parametrize('changed_after_authorization',[False,True])
def test_recovered_workspace_binding_survives_new_process_settings_and_revalidates_identity(installation,tmp_path,changed_after_authorization):
    settings,original_workspace=installation
    # Existing installations use the accepted non-Fresh-Install startup path.
    legacy_style=replace(settings,fresh_install=False)
    service=Maintenance(legacy_style)
    bundle=backup(service)
    plan=approved_restore(service,bundle)
    service.execute_plan(plan['plan_id'],1,'RESTORE_TWOS')
    replacement=tmp_path/'new-authorized-workspace';replacement.mkdir()
    with TestClient(create_app(legacy_style,start_scheduler=False)) as client:
        login(client)
        response=client.post('/api/maintenance/workspace',json={'path':str(replacement),'confirmation':'REAUTHORIZE_WORKSPACE'})
        assert response.status_code==200,response.text
    if changed_after_authorization:
        moved=tmp_path/'moved-workspace';replacement.rename(moved);replacement.symlink_to(moved)
    # A restart reconstructs Settings from the old operator configuration; it
    # does not reuse the mutated Python Settings object from the prior process.
    restarted_settings=replace(legacy_style,source_repo=original_workspace)
    with TestClient(create_app(restarted_settings,start_scheduler=False)) as restarted:
        login(restarted)
        state=restarted.get('/api/maintenance/status').json()
        if changed_after_authorization:
            assert state['authority']['workspace_status']=='REAUTHORIZATION_REQUIRED'
            assert state['standalone'] is True
        else:
            assert restarted.app.state.settings.source_repo==replacement
            assert state['authority']['workspace_status']=='AUTHORIZED'
            assert state['workspace_candidate']==str(replacement)
        assert state['counts']['codex_runs']==0
