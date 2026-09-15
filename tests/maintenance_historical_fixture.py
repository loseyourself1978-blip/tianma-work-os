"""Authentic accepted-tree fixture builder; no terminal row fabrication."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

COMMITS = {
    'vol19.003': '3cf914b6c5667059923ab209f8e9008b33a05cef',
    'vol19.004': 'e51e1c4cd092fd992749c69f83999f994f7faeb4',
}

BUILD = r'''
import json, os, sys, time
from dataclasses import replace
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import text
import tests.test_self_hosting as helpers
import tests.test_vol19_owner_commit_push_delivery as delivery
from twos_runtime.app import create_app
root = Path(sys.argv[1])
schema = sys.argv[2]
password = 'fixture-19-3-local-owner-password'
helpers.OWNER_PASSWORD = password
settings_used = None
if schema == 'vol19.004':
    import inspect
    # The historical helper assumes the developer seed project. First Run
    # canonically creates an authorized workspace project instead. Adapt only
    # that fixture input selection; production history remains untouched.
    task_helper = inspect.getsource(helpers.create_development_task).replace(
        'next(item for item in projects if item["key"] == "twos")', 'projects[0]')
    exec(task_helper, helpers.__dict__)
    from tests.test_vol19_fresh_install_first_run import fresh_settings
    original_make_client = delivery.make_client
    def fresh_client(path, source_repo, runner, **kwargs):
        global settings_used
        # Get the accepted deterministic catalogue from the historical helper;
        # close its independent empty runtime before canonical First Run.
        catalogue_client = original_make_client(path, source_repo, runner,
            database_path=path/'catalogue-only.sqlite3', timeout=30,
            local_verification_command=kwargs['local_verification_command'])
        catalogue = catalogue_client.app.state.codex_manager.adapter._model_catalog_cache
        catalogue_client.app.state.engine.dispose()
        settings = replace(fresh_settings(path), codex_executable=str(runner),
            local_verification_command=kwargs['local_verification_command'], codex_timeout_seconds=30)
        settings_used = settings
        app = create_app(settings, start_scheduler=False)
        app.state.codex_manager.adapter._model_catalog_cache = catalogue
        app.state.codex_manager.adapter._model_catalog_cached_at = time.monotonic()
        return TestClient(app)
    def fresh_login(client):
        s = client.app.state.settings
        assert client.post('/api/setup/start', json={'confirmation':'START_FIRST_RUN'}).status_code == 200
        assert client.post('/api/setup/start', json={'confirmation':'CONFIRM_INSTALLATION'}).status_code == 200
        response = client.post('/api/setup/owner', json={'username':'owner','password':password,
            'password_confirmation':password,'setup_authorization':s.setup_authorization_path.read_text().strip(),
            'request_id':'historical-fixture-owner-193'})
        assert response.status_code == 201, response.text
        response = client.post('/api/setup/workspace', json={'path':str(root/'work'/'source-repo'),'create_if_missing':False})
        assert response.status_code == 200, response.text
        assert client.post('/api/setup/optional-tools',json={'decision':'skip'}).status_code == 200
        assert client.post('/api/setup/finish',json={'confirmation':'FINISH_FIRST_RUN'}).status_code == 200
        return {}
    delivery.make_client = fresh_client
    delivery.init_and_login = fresh_login
with delivery._canonical_applied_delivery(root/'work') as fixture:
    proposal, approval, commit = delivery._commit_delivery(fixture)
    response = fixture.client.post(f"/api/local-commits/{commit['id']}/push-plans",json={})
    assert response.status_code == 200, response.text
    plan = response.json()['push_plan']
    response = fixture.client.post(f"/api/push-plans/{plan['id']}/approvals",json={
        'confirmation':'APPROVE_PUSH_PLAN','expected_plan_digest':plan['advanced']['plan_digest'],
        'expected_plan_version':plan['version']})
    assert response.status_code == 200, response.text
    approval = response.json()['push_approval']
    response = fixture.client.post(f"/api/push-plans/{plan['id']}/push-attempts",json={
        'confirmation':'PUSH_TO_ORIGIN_MAIN','expected_plan_digest':plan['advanced']['plan_digest'],
        'expected_approval_digest':approval['advanced']['approval_digest']})
    assert response.status_code == 200, response.text
    assert delivery._bare_ref(fixture.origin) == commit['commit_oid']
    s = fixture.client.app.state.settings
    with fixture.factory() as session:
        versions = session.execute(text('SELECT version FROM schema_versions')).scalars().all()
        assert schema in versions
    receipt = {'schema':schema, 'database':str(fixture.client.app.state.engine.url.database),
        'source_repo':str(fixture.source_repo), 'worktree_root':str(s.worktree_root),
        'local_remote':str(fixture.origin), 'delivered_sha':commit['commit_oid'], 'run_id':fixture.run_id,
        'username':'owner', 'password':password, 'fresh_install':getattr(s,'fresh_install',False),
        'installation_id':getattr(s,'installation_id',None),
        'bind_port':getattr(s,'bind_port',None), 'session_cookie_name':getattr(s,'session_cookie_name','twos_session')}
    for name in ('data_root','runtime_environment','log_directory','installation_config_path','setup_authorization_path'):
        receipt[name] = str(getattr(s,name)) if getattr(s,name,None) else None
(root/'fixture.json').write_text(json.dumps(receipt))
(root/'fixture.json').chmod(0o600)
'''


def build_historical(schema, root):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    tree = root/'historical-source'
    tree.mkdir(mode=0o700)
    git = shutil.which('git')
    result = subprocess.run([git, 'archive', COMMITS[schema]], capture_output=True, check=True)
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        archive.extractall(tree, filter='data')
    env = {k:v for k,v in os.environ.items() if not k.startswith('GIT_') and k != 'PYTHONPATH'}
    process = subprocess.run([sys.executable, '-c', BUILD, str(root), schema], cwd=tree, env=env, capture_output=True, text=True, timeout=180)
    assert process.returncode == 0, process.stderr[-12000:] + process.stdout[-2000:]
    value = json.loads((root/'fixture.json').read_text())
    value['accepted_commit'] = COMMITS[schema]
    return value
