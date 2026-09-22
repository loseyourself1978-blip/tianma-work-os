from __future__ import annotations

from dataclasses import replace
import errno
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from scripts import twos_bootstrap as bootstrap
from twos_runtime import apply_sessions, codex_adapter, codex_exec_bridge as bridge, self_hosting
from twos_runtime.app import create_app
from twos_runtime.models import User, SessionToken, Schedule, TaskRun, Task, utc_now
from twos_runtime.security import hash_password, hash_token


@pytest.mark.parametrize('operation', ['pid', 'log', 'lock', 'read_pid', 'read_json'])
def test_bootstrap_hardlink_preserves_other_path_bytes_and_mode(tmp_path, operation):
    external = tmp_path / 'owner-file'
    external.write_text('12345\n' if operation != 'read_json' else '{}')
    external.chmod(0o600)
    linked = tmp_path / 'control'
    os.link(external, linked)
    before = external.read_bytes(), external.stat().st_mode
    with pytest.raises(bootstrap.BootstrapError):
        {'pid': lambda: bootstrap.write_pid(linked, 123),
         'log': lambda: bootstrap.append_log(linked, 'write'),
         'lock': lambda: bootstrap.acquire_startup_lock(linked),
         'read_pid': lambda: bootstrap.read_pid(linked),
         'read_json': lambda: bootstrap.read_json(linked)}[operation]()
    assert (external.read_bytes(), external.stat().st_mode) == before


@pytest.mark.parametrize('name', ['_atomic_create_file', '_atomic_replace_file'])
def test_apply_prepare_failure_closes_parent_fd(tmp_path, monkeypatch, name):
    descriptor = os.open(tmp_path, os.O_RDONLY)
    target = tmp_path / 'target'
    target.write_text('preserve')
    monkeypatch.setattr(apply_sessions, '_open_parent_directory', lambda *a: (descriptor, 'target'))
    def fail(*a, **kw):
        raise OSError(errno.ENOSPC, 'injected storage failure')
    monkeypatch.setattr(apply_sessions, '_prepare_temporary_material', fail)
    extra = {'expected': 'before'} if name == '_atomic_replace_file' else {}
    with pytest.raises(OSError, match='injected'):
        getattr(apply_sessions, name)(tmp_path, SimpleNamespace(repository_path='target'), b'new',
                                     0o600, atime_ns=None, mtime_ns=None, **extra)
    with pytest.raises(OSError) as closed:
        os.fstat(descriptor)
    assert closed.value.errno == errno.EBADF
    assert target.read_text() == 'preserve'


def test_local_git_scrubs_redirection_and_unrelated_secrets(tmp_path, monkeypatch):
    from tests.test_self_hosting import make_source_repo, run_command
    (tmp_path / 'one').mkdir()
    (tmp_path / 'two').mkdir()
    repo = make_source_repo(tmp_path / 'one')
    other = make_source_repo(tmp_path / 'two')
    monkeypatch.setenv('GIT_DIR', str(other / '.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(other))
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'core.fsmonitor')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'unsafe')
    monkeypatch.setenv('UNRELATED_SECRET', 'sentinel')
    monkeypatch.setenv('NODE_OPTIONS', 'injection')
    for hardened in (False, True):
        assert Path(self_hosting.run_git(repo, 'rev-parse', '--show-toplevel',
                    hardened_read_only=hardened).stdout.strip()).resolve() == repo.resolve()
    environment = self_hosting._read_only_git_environment()
    assert not {'GIT_DIR', 'GIT_WORK_TREE', 'GIT_CONFIG_COUNT', 'UNRELATED_SECRET', 'NODE_OPTIONS'} & environment.keys()


def test_mixed_bearer_cookie_logout_revokes_authenticated_token(tmp_path):
    from tests.test_owner_auth import make_app, signup, login
    with TestClient(make_app(tmp_path / 'auth.sqlite3')) as client:
        assert signup(client).status_code == 201
        cookie_a = client.cookies.get('twos_session')
        assert login(client).status_code == 200
        bearer_b = client.cookies.get('twos_session')
        client.cookies.set('twos_session', cookie_a)
        assert client.post('/api/auth/logout', headers={'Authorization': 'Bearer ' + bearer_b}).status_code == 200
        assert client.get('/api/auth/me', headers={'Authorization': 'Bearer ' + bearer_b}).status_code == 401


@pytest.mark.parametrize('invalid', ['hash', 'username'])
@pytest.mark.parametrize('standalone', [False, True])
def test_maintenance_invalid_owner_denies_existing_session(tmp_path, invalid, standalone):
    from tests.test_vol19_maintenance import login
    from tests.test_vol19_fresh_install_first_run import fresh_settings, create_owner_and_workspace, finish_setup
    from twos_runtime.maintenance_api import maintenance_app
    settings = fresh_settings(tmp_path)
    with TestClient(create_app(settings, start_scheduler=False)) as client:
        create_owner_and_workspace(client, settings, tmp_path / 'workspace')
        finish_setup(client)
        token = client.cookies.get(settings.session_cookie_name)
        with client.app.state.session_factory() as session:
            owner = session.scalar(select(User))
            if invalid == 'hash': owner.password_hash = ''
            else: owner.username = ''
            session.commit()
        assert client.get('/api/maintenance/status').status_code == 401
    if standalone:
        with TestClient(maintenance_app(settings)) as client:
            assert client.get('/api/maintenance/status', headers={'Authorization': 'Bearer ' + token}).status_code == 401


def test_foreign_task_schedule_and_run_collections_fail_closed(tmp_path):
    from tests.test_owner_auth import make_app, signup
    from datetime import timedelta
    with TestClient(make_app(tmp_path / 'scope.sqlite3')) as client:
        assert signup(client).status_code == 201
        project = client.get('/api/projects').json()[0]['id']
        own = client.post('/api/tasks', json={'project_id': project, 'title': 'own', 'workflow_type': 'general'}).json()['id']
        token = os.urandom(24).hex()
        with client.app.state.session_factory() as session:
            salt_hash, salt = hash_password('fixture-' + os.urandom(18).hex())
            other = User(username='other', password_hash=salt_hash, password_salt=salt, is_active=True)
            session.add(other); session.flush()
            session.add(SessionToken(user_id=other.id, token_hash=hash_token(token),
                                     expires_at=utc_now() + timedelta(hours=1)))
            session.commit()
        headers = {'Authorization': 'Bearer ' + token}
        foreign = client.post('/api/tasks', headers=headers, json={'project_id': project, 'title': 'foreign', 'workflow_type': 'general'}).json()['id']
        schedule = client.post('/api/schedules', headers=headers, json={'task_id': foreign, 'name': 'foreign', 'interval_seconds': 3600}).json()['id']
        created_run = client.post(f'/api/tasks/{foreign}/run', headers=headers, json={'action': 'compact_sync'})
        assert created_run.status_code == 200, created_run.text
        foreign_run = created_run.json()['id']
        assert any(row['id'] == foreign_run for row in client.get('/api/runs', headers=headers).json())
        assert all(row['id'] != foreign_run for row in client.get('/api/runs').json())
        assert all(row['task_id'] != foreign for row in client.get('/api/runs').json())
        assert all(row['id'] != schedule for row in client.get('/api/schedules').json())
        assert client.post('/api/schedules', json={'task_id': foreign, 'name': 'deny', 'interval_seconds': 3600}).status_code == 404
        assert client.patch(f'/api/schedules/{schedule}', json={'run_now': True, 'paused': True}).status_code == 404
        with client.app.state.session_factory() as session:
            assert session.get(Schedule, schedule).paused is False
        client.cookies.clear()
        assert client.post('/api/schedules', json={'task_id': own, 'name': 'deny', 'interval_seconds': 3600}).status_code == 401


def test_codex_detection_projects_environment(tmp_path, monkeypatch):
    from twos_runtime.config import Settings
    executable = tmp_path / 'codex'
    executable.touch()
    seen = []
    def run(argv, **kw):
        seen.append(kw['env'])
        return subprocess.CompletedProcess(argv, 0, stdout='codex 0.144.4' if '--version' in argv else 'exec --json --output-last-message --sandbox --model', stderr='')
    monkeypatch.setenv('UNRELATED_SECRET', 'sentinel')
    monkeypatch.setenv('NODE_OPTIONS', 'injection')
    monkeypatch.setenv('GIT_DIR', 'outside')
    monkeypatch.setattr(codex_adapter.subprocess, 'run', run)
    codex_adapter.CodexAdapter(Settings(database_url='sqlite://', codex_executable=str(executable))).detect()
    assert len(seen) == 2
    assert all(not {'UNRELATED_SECRET', 'NODE_OPTIONS', 'GIT_DIR'} & env.keys() for env in seen)


def test_catalogue_cleanup_reaps_child_and_closes_pipes(tmp_path):
    marker = tmp_path / 'child.pid'
    script = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(90)']); open(sys.argv[1],'w').write(str(p.pid)); time.sleep(90)"
    process = subprocess.Popen([sys.executable, '-c', script, str(marker)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True)
    try:
        for _ in range(100):
            if marker.exists(): break
            time.sleep(.02)
        assert marker.exists()
        child = int(marker.read_text())
        codex_adapter._close_catalog_process(process)
        assert process.poll() is not None
        assert process.stdin.closed and process.stdout.closed
        for _ in range(100):
            result = subprocess.run(['ps', '-o', 'stat=', '-p', str(child)], capture_output=True, text=True)
            assert result.returncode in {0, 1}, result.stderr
            if not result.stdout.strip() or result.stdout.strip().startswith('Z'): break
            time.sleep(.02)
        else: pytest.fail('catalogue descendant survived')
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL); process.wait()


@pytest.mark.parametrize('leader_exits', [False, True])
def test_catalogue_cleanup_kills_term_ignoring_descendant_after_leader_exit(tmp_path, leader_exits):
    marker = tmp_path / 'child-ready'
    child_script = (
        "import os,signal,sys,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        "open(sys.argv[1],'w').write(str(os.getpid())); time.sleep(90)"
    )
    parent_script = (
        "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]]); "
        + ("time.sleep(.1)" if leader_exits else "time.sleep(90)")
    )
    process = subprocess.Popen([sys.executable, '-c', parent_script, child_script, str(marker)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True)
    try:
        deadline = time.monotonic() + 5
        while not marker.exists():
            assert time.monotonic() < deadline
            time.sleep(.01)
        child = int(marker.read_text())
        if leader_exits:
            # Observe without poll/wait so the group leader stays unreaped.
            while True:
                result = subprocess.run(['/bin/ps', '-p', str(process.pid), '-o', 'stat='],
                    check=True, capture_output=True, text=True)
                if result.stdout.strip().startswith('Z'):
                    break
                assert time.monotonic() < deadline
                time.sleep(.01)
        codex_adapter._close_catalog_process(process)
        assert process.returncode is not None
        assert process.stdin.closed and process.stdout.closed
        result = subprocess.run(['/bin/ps', '-p', str(child), '-o', 'stat='], capture_output=True, text=True)
        assert result.returncode in {0, 1}, result.stderr
        assert not result.stdout.strip() or result.stdout.strip().startswith('Z')
    finally:
        if process.returncode is None:
            codex_adapter._close_catalog_process(process)


def test_catalogue_cleanup_does_not_swallow_live_group_permission_denial(monkeypatch):
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True)
    calls = []
    def denied(pgid, stop_signal):
        calls.append((pgid, stop_signal))
        raise PermissionError('controlled live-group denial')
    try:
        with monkeypatch.context() as changes:
            changes.setattr(codex_adapter.os, 'killpg', denied)
            with pytest.raises(PermissionError, match='controlled live-group denial'):
                codex_adapter._close_catalog_process(process)
        assert calls == [(process.pid, signal.SIGTERM)]
        assert process.returncode is None
        assert codex_adapter._catalog_group_has_live_members(process)
    finally:
        codex_adapter._close_catalog_process(process)
    assert process.returncode is not None


def test_catalogue_cleanup_checks_exit_after_signal_permission_race(monkeypatch):
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, start_new_session=True)
    original = os.killpg
    calls = []
    def already_exited(pgid, stop_signal):
        calls.append((pgid, stop_signal))
        original(pgid, stop_signal)
        deadline = time.monotonic() + 2
        while codex_adapter._catalog_group_has_live_members(process):
            assert time.monotonic() < deadline
            time.sleep(.01)
        raise PermissionError('macOS exited-group race')
    try:
        with monkeypatch.context() as changes:
            changes.setattr(codex_adapter.os, 'killpg', already_exited)
            codex_adapter._close_catalog_process(process)
        assert calls == [(process.pid, signal.SIGTERM)]
        assert process.returncode == -signal.SIGTERM
        assert process.stdin.closed and process.stdout.closed
        # Repeated cleanup of a reaped, absent group sends no new signal.
        codex_adapter._close_catalog_process(process)
    finally:
        if process.returncode is None:
            codex_adapter._close_catalog_process(process)


def test_catalogue_cleanup_refuses_nonowned_process_group(monkeypatch):
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        def forbidden(*args):
            pytest.fail('must not signal the test parent process group')
        with monkeypatch.context() as changes:
            changes.setattr(codex_adapter.os, 'killpg', forbidden)
            with pytest.raises(RuntimeError, match='does not own'):
                codex_adapter._close_catalog_process(process)
    finally:
        process.terminate(); process.wait(timeout=5)


def test_missing_codex_child_identity_reaps_unpublished_process(tmp_path, monkeypatch):
    from tests.test_vol18_codex_exec_bridge import _prepare
    handle, _, _ = _prepare(tmp_path, 'import time\ntime.sleep(90)\n', phase_key='missing-child-identity')
    spawned = []
    original_popen, original_capture = bridge.subprocess.Popen, bridge.capture_process_start_identity
    def popen(*args, **kw):
        process = original_popen(*args, **kw)
        if kw.get('start_new_session'): spawned.append(process)
        return process
    def identity(pid):
        return '' if spawned and pid == spawned[-1].pid else original_capture(pid)
    monkeypatch.setattr(bridge.subprocess, 'Popen', popen)
    monkeypatch.setattr(bridge, 'capture_process_start_identity', identity)
    try:
        with pytest.raises(bridge.CodexExecBridgeError) as blocked:
            bridge.run_execution(handle)
        assert blocked.value.code == 'PROCESS_IDENTITY_UNAVAILABLE'
        assert len(spawned) == 1 and spawned[0].poll() is not None
        assert all(pipe.closed for pipe in (spawned[0].stdin, spawned[0].stdout, spawned[0].stderr))
    finally:
        for process in spawned:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()


def test_bootstrap_environment_is_minimal_and_package_config_is_scoped(monkeypatch):
    for key in ('UNRELATED_SECRET', 'GIT_DIR', 'PYTHONPATH', 'NODE_OPTIONS', 'OPENAI_API_KEY', 'DYLD_INSERT_LIBRARIES'):
        monkeypatch.setenv(key, 'sentinel')
    monkeypatch.setenv('PIP_INDEX_URL', 'https://package.example.invalid/simple')
    for package in (False, True):
        projected = bootstrap.bootstrap_environment(package_install=package)
        assert not {'UNRELATED_SECRET', 'GIT_DIR', 'PYTHONPATH', 'NODE_OPTIONS', 'OPENAI_API_KEY', 'DYLD_INSERT_LIBRARIES'} & projected.keys()
        assert ('PIP_INDEX_URL' in projected) is package


def test_catalogue_branches_project_environment(tmp_path, monkeypatch):
    from twos_runtime.config import Settings
    executable = tmp_path / 'codex'
    executable.touch()
    seen = []
    def popen(argv, **kw):
        seen.append(('app-server', kw['env']))
        assert kw['start_new_session'] is True
        raise OSError('local catalogue unavailable')
    def run(argv, **kw):
        seen.append(('run', kw['env']))
        return subprocess.CompletedProcess(argv, 0, stdout='codex 0.144.4' if '--version' in argv else '{}', stderr='')
    monkeypatch.setenv('UNRELATED_SECRET', 'sentinel')
    monkeypatch.setenv('NODE_OPTIONS', 'injection')
    monkeypatch.setattr(codex_adapter.subprocess, 'Popen', popen)
    monkeypatch.setattr(codex_adapter.subprocess, 'run', run)
    codex_adapter.CodexAdapter(Settings(database_url='sqlite://', codex_executable=str(executable))).model_catalog()
    assert any(kind == 'app-server' for kind, _env in seen)
    assert len(seen) == 4
    assert all(not {'UNRELATED_SECRET', 'NODE_OPTIONS'} & env.keys() for _kind, env in seen)


def test_runtime_preserves_only_explicit_ssh_agent_context(tmp_path, monkeypatch):
    monkeypatch.setenv('SSH_AUTH_SOCK', str(tmp_path / 'agent.sock'))
    monkeypatch.setenv('SSH_ASKPASS', 'untrusted-helper')
    child = bootstrap.child_environment(tmp_path / 'source', tmp_path / 'data', tmp_path / 'runtime',
        tmp_path / 'logs', {'installation_id': 'install_' + 'a' * 32, 'port': 18080})
    assert child['SSH_AUTH_SOCK'] == str(tmp_path / 'agent.sock')
    assert 'SSH_ASKPASS' not in child
    assert 'SSH_AUTH_SOCK' not in bootstrap.bootstrap_environment()


def test_commit_environment_excludes_unrelated_credentials(monkeypatch):
    from twos_runtime.commit_builder import _git_environment
    for key in ('UNRELATED_SECRET', 'OPENAI_API_KEY', 'GIT_DIR', 'NODE_OPTIONS'):
        monkeypatch.setenv(key, 'sentinel')
    projected = _git_environment(index_file=Path('/controlled/index'))
    assert not {'UNRELATED_SECRET', 'OPENAI_API_KEY', 'GIT_DIR', 'NODE_OPTIONS'} & projected.keys()
    assert projected['GIT_INDEX_FILE'] == '/controlled/index'


def test_atomic_control_publication_failure_removes_temporary(tmp_path, monkeypatch):
    target = tmp_path / 'config.json'
    target.write_text('preserve')
    def fail(*a, **kw):
        raise OSError('injected replacement failure')
    monkeypatch.setattr(bootstrap.os, 'replace', fail)
    with pytest.raises(OSError, match='injected'):
        bootstrap.atomic_private_json(target, {'state': 'new'})
    assert target.read_text() == 'preserve'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['config.json']
