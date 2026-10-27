"""Real maintenance/HTTP boundary; candidate bytes are explicitly synthetic.

No provider, model build, installed Owner database or update is used here.
"""
import hashlib
import json
import os
import threading
from pathlib import Path

import pytest

from tests.test_vol20_r2_project_first import product, project, task
from twos_runtime.project_first import preference
from twos_runtime.project_first_models import WorkExecution, WorkItem


def ready_candidate(product, tmp_path):
    client, app, settings = product
    project_id = project(client, 'Synthetic update candidate', 'development')
    work = task(client, project_id)
    artifact = tmp_path / 'synthetic-candidate.dmg'
    artifact.write_bytes(b'synthetic candidate, never installed')
    receipt = {'artifact': str(artifact), 'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
               'source_commit': 'a' * 40, 'build': 'fixture.1', 'self_iteration_test_artifact': True}
    with app.state.session_factory() as session:
        row = session.get(WorkItem, work['id'])
        row.kind = 'iteration'
        row.state = 'CANDIDATE_READY'
        session.add(WorkExecution(id='synthetic-build', work_id=row.id, revision=1,
            phase='candidate', idempotency_key='synthetic-build', plan_hash=row.plan_hash,
            state='COMPLETED', input_json='{}', evidence_json=json.dumps(receipt),
            started_at=row.created_at, finished_at=row.created_at))
        session.commit()
    return client, app, settings, work['id'], receipt


def test_update_prepare_uses_real_backup_and_persists_review(product, tmp_path):
    client, app, settings, wid, candidate = ready_candidate(product, tmp_path)
    response = client.post(f'/api/r2/iterations/{wid}/update/prepare', json={})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['candidate'] == candidate
    assert result['method'] == 'OWNER_GUI_DMG' and result['installed'] is False
    assert result['backup']['state'] == 'BACKUP_COMPLETE'
    inspected = app.state.maintenance.inspect_backup(result['backup']['backup'])
    assert inspected['manifest']['completion'] == 'SEALED'
    assert Path(result['backup']['backup'], 'database.sqlite3').is_file()
    with app.state.session_factory() as session:
        assert preference(session, 'update_preview:' + wid) == result
        assert preference(session, 'pending_update') is None
    assert app.state.maintenance_busy is False
    assert app.state.result_intake_monitor._thread.is_alive()
    assert client.get('/api/r2/projects').status_code == 200
    assert app.state.project_execution.jobs == {}


@pytest.mark.parametrize('condition,code', [
    ('not_ready', 'CANDIDATE_NOT_READY'), ('changed_artifact', 'CANDIDATE_INPUT_CHANGED'),
    ('missing_receipt', 'CANDIDATE_NOT_READY'), ('wrong_plan', 'CANDIDATE_NOT_READY'),
    ('foreign_project', 'PROJECT_NOT_FOUND'), ('cross_origin', 'ORIGIN_MISMATCH'),
    ('logged_out', 'AUTH_REQUIRED'), ('active_record', 'ACTIVE_OPERATION'),
    ('settling_worker', 'ACTIVE_OPERATION'), ('external_connection', 'INSTALLATION_BUSY'),
])
def test_update_prepare_fail_closed_before_backup(product, tmp_path, condition, code):
    from twos_runtime.maintenance import open_lock
    from twos_runtime.project_first_models import ProjectSpace
    client, app, _, wid, candidate = ready_candidate(product, tmp_path)
    headers = {}
    lease = None
    with app.state.session_factory() as session:
        work = session.get(WorkItem, wid)
        row = session.get(WorkExecution, 'synthetic-build')
        if condition == 'not_ready': work.state = 'BUILT'
        if condition == 'missing_receipt': session.delete(row)
        if condition == 'wrong_plan': row.plan_hash = 'different-plan'
        if condition == 'foreign_project': session.get(ProjectSpace, work.project_id).owner_id = 999
        if condition == 'active_record': row.state = 'RUNNING'
        session.commit()
    if condition == 'changed_artifact': Path(candidate['artifact']).write_bytes(b'changed')
    if condition == 'cross_origin': headers['Origin'] = 'http://foreign.invalid'
    if condition == 'logged_out': client.cookies.clear()
    if condition == 'settling_worker': app.state.project_execution.jobs['synthetic'] = {}
    if condition == 'external_connection': lease = open_lock(app.state.maintenance.db)
    try:
        response = client.post(f'/api/r2/iterations/{wid}/update/prepare', json={}, headers=headers)
        assert response.status_code in (401, 403, 404, 409), response.text
        assert response.json()['error']['code'] == code
        assert app.state.maintenance.journal()['state'] == 'NONE'
        with app.state.session_factory() as session:
            assert preference(session, 'update_preview:' + wid) is None
        assert app.state.maintenance_busy is False
    finally:
        app.state.project_execution.jobs.pop('synthetic', None)
        if lease is not None: os.close(lease)


def test_backup_write_failure_is_visible_and_explicit_retry_can_recover(product, tmp_path):
    from twos_runtime.maintenance import MaintenanceError
    client, app, _, wid, _ = ready_candidate(product, tmp_path)
    def fail_copy(boundary):
        if boundary == 'backup_during_copy':
            raise MaintenanceError('SYNTHETIC_DISK_FAILURE', 'Synthetic backup disk failure.')
    app.state.maintenance.fault = fail_copy
    response = client.post(f'/api/r2/iterations/{wid}/update/prepare', json={})
    assert response.status_code == 409 and response.json()['error']['code'] == 'SYNTHETIC_DISK_FAILURE'
    assert app.state.maintenance.journal()['state'] == 'BACKUP_FAILED'
    assert app.state.maintenance_busy is False
    assert app.state.result_intake_monitor._thread.is_alive()
    with app.state.session_factory() as session:
        assert preference(session, 'update_preview:' + wid) is None
        assert session.get(WorkItem, wid).state == 'CANDIDATE_READY'
    app.state.maintenance.fault = lambda _: None
    response = client.post(f'/api/r2/iterations/{wid}/update/prepare', json={})
    assert response.status_code == 200, response.text
    assert response.json()['backup']['state'] == 'BACKUP_COMPLETE'


def test_preparation_excludes_overlapping_actions_and_never_installs(product, tmp_path):
    client, app, _, wid, _ = ready_candidate(product, tmp_path)
    entered, release = threading.Event(), threading.Event()
    responses = []
    def hold(boundary):
        if boundary == 'backup_before_snapshot':
            entered.set()
            assert release.wait(10)
    app.state.maintenance.fault = hold
    thread = threading.Thread(target=lambda: responses.append(client.post(
        f'/api/r2/iterations/{wid}/update/prepare', json={})))
    thread.start()
    try:
        assert entered.wait(5)
        second = client.post(f'/api/r2/iterations/{wid}/update/prepare', json={})
        assert second.status_code == 409 and second.json()['error']['code'] == 'MAINTENANCE_BUSY'
        assert client.get('/api/r2/projects').status_code == 409
    finally:
        release.set()
        thread.join(10)
    assert not thread.is_alive()
    assert responses[0].status_code == 200, responses[0].text
    with app.state.session_factory() as session:
        assert preference(session, 'pending_update') is None
    assert client.get('/api/r2/projects').status_code == 200
