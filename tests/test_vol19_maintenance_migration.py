from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.maintenance_historical_fixture import build_historical
from twos_runtime.app import create_app
from twos_runtime.config import Settings
from twos_runtime.db import initialize_database, make_engine
from twos_runtime.maintenance import Maintenance, MaintenanceError, inspect_database, logical_digest, snapshot, verify_preserved_data, readonly


@pytest.fixture(scope='module', params=['vol19.003', 'vol19.004'])
def historical(request, tmp_path_factory):
    return build_historical(request.param, tmp_path_factory.mktemp('authentic-'+request.param))


def copy_legacy(historical, root):
    db = root/'legacy.sqlite3'
    snapshot(Path(historical['database']), db)
    return Settings(database_url='sqlite:///'+str(db), source_repo=Path(historical['source_repo']),
        worktree_root=Path(historical['worktree_root']), maintenance_mode=True)


def test_genuine_accepted_state_migrates_preserving_logical_data_and_no_authority_promotion(historical, tmp_path):
    settings = copy_legacy(historical, tmp_path)
    service = Maintenance(settings)
    assert inspect_database(service.db)['schema'] == historical['schema']
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        response = client.post('/api/auth/login', json={'username':historical['username'],'password':historical['password']})
        assert response.status_code == 200, response.text
        state = client.get('/api/maintenance/status').json()
        assert state['schema'] == historical['schema']
        assert state['counts']['codex_runs'] == state['counts']['push_executions'] == 1
        plan = client.post('/api/maintenance/migration-plan', json={}).json()
        assert plan['from_schema'] == historical['schema'] and plan['to_schema'] == 'vol20.001'
        approved = client.post('/api/maintenance/approve-plan', json={'plan_id':plan['plan_id'],'confirmation':'APPROVE_MAINTENANCE_PLAN'})
        assert approved.status_code == 200, approved.text
        result = client.post('/api/maintenance/confirm', json={'plan_id':plan['plan_id'],'confirmation':'MIGRATE_TWOS'})
        assert result.status_code == 200, result.text
        assert result.json()['state'] == 'MIGRATION_COMPLETE'
    # The explicit maintenance login legitimately created a new session before
    # migration. Compare the actual pre-migration recovery point, including it.
    verify_preserved_data(service.root/'prior.sqlite3', service.db)
    with readonly(service.db) as connection:
        expected_owner = 1 if historical['schema'] == 'vol19.005' else None
        assert connection.execute('SELECT owner_user_id FROM tasks').fetchone()[0] == expected_owner
        assert connection.execute('SELECT COUNT(*) FROM guided_tool_configurations').fetchone()[0] == 0
        assert connection.execute('SELECT status FROM codex_runs').fetchone()[0] == 'completed'
        assert connection.execute('SELECT state FROM push_executions').fetchone()[0] == 'PUSHED'
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        assert client.post('/api/auth/login',json={'username':historical['username'],'password':historical['password']}).status_code == 200
        assert client.get('/api/maintenance/status').json()['schema'] == 'vol20.001'
        assert client.post('/api/maintenance/migration-plan',json={}).status_code == 409


@pytest.mark.parametrize('boundary', ['migration_step', 'migration_after_step', 'migration_before_activation', 'migration_post_verify'])
def test_migration_exception_preserves_last_good_state(historical, tmp_path, boundary):
    settings = copy_legacy(historical, tmp_path)
    service = Maintenance(settings)
    before = logical_digest(service.db)
    plan = service.migration_plan(1); service.approve_plan(plan['plan_id'],1)
    service.fault = lambda at: (_ for _ in ()).throw(RuntimeError('injected migration failure')) if at == boundary else None
    with pytest.raises(RuntimeError): service.execute_plan(plan['plan_id'],1,'MIGRATE_TWOS')
    assert service.journal()['state'] == 'MIGRATION_FAILED'
    assert logical_digest(service.db) == before
    Maintenance(settings).reconcile()
    assert inspect_database(service.db)['schema'] == historical['schema']
    engine = make_engine(settings.database_url)
    try:
        with pytest.raises(MaintenanceError, match='previous migration'):
            initialize_database(engine)
    finally: engine.dispose()


@pytest.mark.parametrize('boundary,activated', [('migration_after_step',False), ('migration_after_activation',True)])
def test_migration_process_interruption_is_observably_reconciled(historical, tmp_path, boundary, activated):
    settings = copy_legacy(historical,tmp_path)
    service = Maintenance(settings)
    plan = service.migration_plan(1); service.approve_plan(plan['plan_id'],1)
    code = '''import os,sys
from twos_runtime.config import Settings
from twos_runtime.maintenance import Maintenance
s=Maintenance(Settings(database_url=sys.argv[1]),fault=lambda at:os._exit(74) if at==sys.argv[2] else None)
s.execute_plan(sys.argv[3],1,'MIGRATE_TWOS')
'''
    result = subprocess.run([sys.executable,'-c',code,settings.database_url,boundary,plan['plan_id']],capture_output=True)
    assert result.returncode == 74, result.stderr.decode()
    service.reconcile()
    assert service.journal()['state'] == 'RECOVERY_COMPLETE'
    assert inspect_database(service.db)['schema'] == ('vol20.001' if activated else historical['schema'])
    assert not (service.root/'staged.sqlite3').exists()
    verify_preserved_data(Path(historical['database']),service.db)


@pytest.mark.parametrize('damage', ['future','missing_marker','foreign_key'])
def test_invalid_historical_schema_is_rejected_without_mutation(historical,tmp_path,damage):
    settings=copy_legacy(historical,tmp_path)
    service=Maintenance(settings)
    with closing(sqlite3.connect(service.db)) as connection:
        if damage=='future': connection.execute("UPDATE schema_versions SET version='vol99.001' WHERE version=?",(historical['schema'],))
        elif damage=='missing_marker': connection.execute("DELETE FROM schema_versions WHERE version='vol18.001'")
        else: connection.execute("UPDATE tasks SET project_id=999999")
        connection.commit()
    before=logical_digest(service.db)
    with pytest.raises(MaintenanceError): service.migration_plan(1)
    assert logical_digest(service.db)==before


def test_current_backup_restore_retains_full_accepted_delivery_and_prevents_replay(historical,tmp_path):
    from dataclasses import replace
    settings=copy_legacy(historical,tmp_path)
    service=Maintenance(settings)
    migration=service.migration_plan(1);service.approve_plan(migration['plan_id'],1)
    service.execute_plan(migration['plan_id'],1,'MIGRATE_TWOS')
    created=service.create_backup()
    inspected=service.inspect_backup(created['backup'])
    assert any(name.startswith('result-material/') for name in inspected['manifest']['files'])
    with closing(sqlite3.connect(service.db)) as connection:
        connection.execute("UPDATE tasks SET title='post-backup mutation'");connection.commit()
    plan=service.restore_plan(created['backup'],1);service.approve_plan(plan['plan_id'],1)
    service.execute_plan(plan['plan_id'],1,'RESTORE_TWOS')
    with readonly(service.db) as connection:
        assert connection.execute('SELECT title FROM tasks').fetchone()[0]!='post-backup mutation'
        for table in ('codex_runs','codex_result_envelopes','apply_sessions','post_apply_verifications','local_commit_executions','push_executions'):
            assert connection.execute('SELECT COUNT(*) FROM '+table).fetchone()[0]==1
        assert connection.execute('SELECT state FROM push_executions').fetchone()[0]=='PUSHED'
    # Rebackup does not need to reactivate a source worktree. The restored
    # inert archive/journal retains exact attributed bytes and sealed hashes.
    second=service.create_backup()
    assert service.inspect_backup(second['backup'])['integrity_status']=='VERIFIED'
    with TestClient(create_app(settings,start_scheduler=False)) as client:
        assert client.post('/api/auth/login',json={'username':historical['username'],'password':historical['password']}).status_code==200
        response=client.post('/api/maintenance/workspace',json={'path':historical['source_repo'],'confirmation':'REAUTHORIZE_WORKSPACE'})
        assert response.status_code==200,response.text
    with TestClient(create_app(replace(settings,maintenance_mode=False),start_scheduler=False)) as client:
        assert client.post('/api/auth/login',json={'username':historical['username'],'password':historical['password']}).status_code==200
        paths = ['/api/codex-runs/1/delivery-review/accept', '/api/tasks/1/codex-packs/1/approve']
        with readonly(service.db) as connection:
            for table, column, suffix, route in (
                ('apply_plans','plan_id','apply-sessions','apply-plans'),
                ('apply_sessions','session_id','reverts','apply-sessions'),
                ('post_apply_verifications','verification_id','commit-proposals','post-apply-verifications'),
                ('commit_plans','commit_plan_id','stage-sessions','commit-plans'),
                ('commit_proposals','proposal_id','local-commits','commit-proposals'),
                ('local_commit_executions','commit_execution_id','push-plans','local-commits'),
                ('push_plans','push_plan_id','push-attempts','push-plans'),
                ('push_executions','push_execution_id','push-attempts','push-preflights'),
                ('handoff_instruction_drafts','draft_id','approve','instruction-drafts'),
                ('owner_acceptance_sessions','id','accept','owner-acceptance')):
                for row in connection.execute('SELECT "'+column+'" FROM "'+table+'"'):
                    paths.append('/api/'+route+'/'+str(row[0])+'/'+suffix)
        assert any('/push-plans/' in path for path in paths)
        assert any('/apply-plans/' in path for path in paths)
        for path in paths:
            response=client.post(path,json={})
            assert response.status_code==409,(path,response.text)
            assert response.json()['error']['code']=='HISTORICAL_EVIDENCE_ONLY'
        assert client.post('/api/tasks/1/codex-packs',json={}).status_code==428
        assert client.get('/api/maintenance/data').json()['counts']['push_executions']==1


@pytest.mark.parametrize('seed', [False, True])
def test_existing_partial_engine_migration_has_recovery_point_and_preserves_seed_option(tmp_path, seed):
    from tests.test_model_orchestration import partial_model_registry_database
    engine = partial_model_registry_database(tmp_path, 'configuration_status', 'configured')
    service = Maintenance(Settings(database_url=str(engine.url)))
    original = logical_digest(service.db)
    try:
        initialize_database(engine, seed_default_projects=seed)
        receipt = service.journal()
        assert receipt['state'] == 'MIGRATION_COMPLETE'
        assert receipt['initiator'] == 'EXISTING_STARTUP_ENGINE'
        assert not (service.root/'approval.json').exists()
        assert logical_digest(service.root/'prior.sqlite3') == original
        with readonly(service.db) as connection:
            assert connection.execute('SELECT COUNT(*) FROM projects').fetchone()[0] == (3 if seed else 0)
            assert connection.execute('SELECT configuration_status FROM ai_models WHERE id=72').fetchone()[0] == 'configured'
        initialize_database(engine, seed_default_projects=seed)
        assert service.journal()['operation_id'] == receipt['operation_id']
    finally:
        engine.dispose()


def test_existing_partial_engine_failure_does_not_retry_or_lose_original(tmp_path, monkeypatch):
    from tests.test_model_orchestration import partial_model_registry_database
    from twos_runtime import db as database_module
    engine = partial_model_registry_database(tmp_path, 'availability_status', 'available')
    service = Maintenance(Settings(database_url=str(engine.url)))
    original = logical_digest(service.db)
    real = database_module._initialize_database
    def broken(staged_engine, **kwargs):
        real(staged_engine, **kwargs)
        raise RuntimeError('injected existing engine migration failure')
    monkeypatch.setattr(database_module, '_initialize_database', broken)
    try:
        with pytest.raises(RuntimeError):
            initialize_database(engine)
        assert service.journal()['state'] == 'MIGRATION_FAILED'
        assert logical_digest(service.db) == original
        monkeypatch.setattr(database_module, '_initialize_database', real)
        with pytest.raises(MaintenanceError, match='previous migration'):
            initialize_database(engine)
        assert logical_digest(service.db) == original
    finally:
        engine.dispose()


def test_existing_partial_engine_process_interruption_recovers_before_teardown(tmp_path):
    from tests.test_model_orchestration import partial_model_registry_database
    engine = partial_model_registry_database(tmp_path, 'availability_status', 'available')
    service = Maintenance(Settings(database_url=str(engine.url)))
    engine.dispose()
    original = logical_digest(service.db)
    code = """import os,sys
from twos_runtime import db
real=db._initialize_database
def interrupted(engine,**kwargs):
    real(engine,**kwargs)
    os._exit(75)
db._initialize_database=interrupted
db.initialize_database(db.make_engine(sys.argv[1]))
"""
    result = subprocess.run([sys.executable, '-c', code, str(engine.url)], capture_output=True)
    assert result.returncode == 75, result.stderr.decode()
    service.reconcile()
    assert service.journal()['state'] == 'RECOVERY_COMPLETE'
    assert logical_digest(service.db) == original
    assert not (service.root/'staged.sqlite3').exists()
    try:
        with pytest.raises(MaintenanceError, match='previous migration'):
            initialize_database(engine)
    finally:
        engine.dispose()


def test_result_material_omission_is_rejected_even_with_resealed_manifest(historical,tmp_path):
    from twos_runtime.maintenance import read_json, atomic_json, digest
    settings=copy_legacy(historical,tmp_path)
    service=Maintenance(settings)
    plan=service.migration_plan(1); service.approve_plan(plan['plan_id'],1)
    service.execute_plan(plan['plan_id'],1,'MIGRATE_TWOS')
    bundle=Path(service.create_backup()['backup'])
    manifest=read_json(bundle/'manifest.json')
    name=next(n for n in manifest['files'] if n.startswith('result-material/'))
    (bundle/name).unlink(); del manifest['files'][name]
    manifest['integrity']=digest({k:v for k,v in manifest.items() if k!='integrity'})
    atomic_json(bundle/'manifest.json',manifest)
    before=logical_digest(service.db)
    with pytest.raises(MaintenanceError) as rejected:
        service.inspect_backup(str(bundle))
    assert rejected.value.code=='RESULT_MATERIAL_MISSING'
    assert logical_digest(service.db)==before


def test_generic_migration_snapshot_failure_exposes_unchanged_old_database(tmp_path, monkeypatch):
    import twos_runtime.maintenance as maintenance_module
    from tests.test_model_orchestration import partial_model_registry_database
    engine=partial_model_registry_database(tmp_path,'configuration_status','configured')
    service=Maintenance(Settings(database_url=str(engine.url)))
    before=logical_digest(service.db)
    monkeypatch.setattr(maintenance_module,'snapshot',lambda *a,**k: (_ for _ in ()).throw(OSError('injected snapshot failure')))
    try:
        with pytest.raises(OSError):
            initialize_database(engine)
        state=service.status()
        assert state['recovery_only'] and state['active_unchanged']
        assert not state['recovery_point_verified']
        assert state['recovery_point']==str(service.db)
        assert 'no completed snapshot' in state['next_action']
        assert logical_digest(service.db)==before
    finally:
        engine.dispose()


def test_accepted_ga_baseline_19005_migrates_without_losing_history(tmp_path):
    historical = build_historical('vol19.005', tmp_path/'baseline')
    destination = tmp_path/'new-schema'; destination.mkdir()
    test_genuine_accepted_state_migrates_preserving_logical_data_and_no_authority_promotion(historical, destination)
