from __future__ import annotations

import json
import os
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from tests.test_self_hosting import (
    make_source_repo, make_fake_codex, make_client, init_and_login,
    run_command, approve_pack, start_codex_run, wait_for_run,
)
from tests.test_vol19_result_owner_delivery import _decision_payload
from tests.test_vol19_verification_truth_remediation import make_local_verifier, _result_envelope
from twos_runtime.codex_adapter import CodexAdapter
from twos_runtime.config import Settings
from twos_runtime.guided_delivery import discovery, pack_binding
from twos_runtime.models import CodexInstructionPack, CodexRun, SessionToken, User, utc_now
from twos_runtime.security import hash_password, hash_token

BEFORE = 'TWOS VOL19 FIRST SAFE DELIVERY BEFORE\n'
AFTER = 'TWOS VOL19 FIRST SAFE DELIVERY PASS\n'
MODEL = 'gpt-6-astra'
CHOICE = {'model_identifier': MODEL, 'reasoning_effort': 'xhigh'}


@pytest.fixture(autouse=True)
def no_inherited_git_overrides(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith('GIT_'):
            monkeypatch.delenv(name, raising=False)


def git(repo, *args):
    return run_command(repo, 'git', *args).stdout.strip()


def local_runner(root: Path, *, version='0.153.4', fault=''):
    executable = make_fake_codex(root)
    script = executable.read_text().replace('codex-cli 0.144.4', 'codex-cli ' + version)
    script = script.replace('codex-result.txt', 'first_delivery.txt').replace('isolated result\\n', AFTER.replace('\n', '\\n'))
    prefix = '''
if sys.argv[1:] == ['debug', 'models', '--bundled']:
    print(json.dumps({'models': [{'slug': 'gpt-6-astra', 'visibility': 'list', 'supported_reasoning_levels': [{'effort': x} for x in ['low', 'high', 'xhigh', 'max', 'ultra']]}]}))
    raise SystemExit(0)
if '-c' in sys.argv:
    pos = sys.argv.index('-c')
    assert sys.argv[pos + 1] in ['model_reasoning_effort="xhigh"', 'model_reasoning_effort="max"']
    pathlib.Path(__file__).with_suffix('.reasoning').write_text(sys.argv[pos + 1])
    del sys.argv[pos:pos + 2]
'''
    if fault == 'auth':
        prefix += "if sys.argv[1:] == ['login', 'status']:\n    print('Not logged in', file=sys.stderr)\n    raise SystemExit(1)\n"
    elif fault in {'network', 'model', 'secret'}:
        message = {'network': 'network unreachable', 'model': 'requested model unavailable',
                   'secret': 'network unreachable token=sk-fixture-secret-012345678901234567890123456789'}[fault]
        prefix += f"if sys.argv[1:2] == ['exec'] and '--help' not in sys.argv:\n    print({message!r}, file=sys.stderr)\n    raise SystemExit(1)\n"
    script = script.replace('import time\n', 'import time\n' + prefix, 1)
    executable.write_text(script)
    return executable


def environment(root: Path, *, fault=''):
    repo = make_source_repo(root)
    (repo / 'first_delivery.txt').write_text(BEFORE)
    git(repo, 'add', 'first_delivery.txt')
    git(repo, 'commit', '-m', 'first delivery baseline')
    runner = local_runner(root, fault=fault)
    verifier = make_local_verifier(root)
    path = Path(verifier[1])
    path.write_text(path.read_text().replace('codex-result.txt', 'first_delivery.txt').replace('isolated result\\n', AFTER.replace('\n', '\\n')))
    return repo, runner, verifier


def create_task(client, title='First Safe Delivery'):
    project = client.get('/api/projects').json()[0]['id']
    result = client.post('/api/tasks', json={'project_id': project, 'title': title,
        'workflow_type': 'general', 'objective': 'Change first_delivery.txt to the required PASS text.',
        'required_output': AFTER.strip(), 'implementation_scope': 'first_delivery.txt only',
        'acceptance_target': 'Independent exact-content check passes.',
        'forbidden_scope': 'No Commit, Push, Force, tag, network Git remote, or unrelated file changes.'})
    assert result.status_code == 200, result.text
    return result.json()['id']


def check_and_save(client, choice=None):
    response = client.post('/api/guided-tool-setup/check', json=choice or CHOICE)
    assert response.status_code == 200, response.text
    config = response.json()['configuration']
    assert config['ready'] is True, response.text
    assert config['confirmed'] is False
    saved = client.post('/api/guided-tool-setup/save', json={'configuration_id': config['id']})
    assert saved.status_code == 200, saved.text
    assert saved.json()['configuration']['confirmed'] is True
    return config


def counts(client):
    with client.app.state.session_factory() as session:
        return {table: session.execute(text('select count(*) from ' + table)).scalar_one()
                for table in ('codex_instruction_packs', 'codex_runs', 'apply_sessions', 'local_commit_executions', 'push_executions')}


@pytest.mark.parametrize('version,status', [('0.100.0', 'Needs Upgrade'), ('0.144.3', 'Needs Upgrade'),
    ('0.144.4', 'Not checked'), ('0.153.4', 'Not checked'), ('garbage', 'Needs Setup')])
def test_cli_version_is_truthful_and_minimum_is_enforced(tmp_path, version, status):
    runner = local_runner(tmp_path, version=version)
    found = discovery(CodexAdapter(Settings(database_url='sqlite://', codex_executable=str(runner))))
    assert found['status'] == status
    assert found['minimum_supported_version'] == '0.144.4'
    assert found['provider_request_performed'] is False
    if version == '0.153.4':
        assert found['cli_version'] == 'codex-cli 0.153.4'
        assert found['models'][0]['reasoning_efforts'] == ['low', 'high', 'xhigh', 'max']
    assert not runner.with_name(runner.name + '.probe-executed').exists()


def test_missing_cli_needs_setup(tmp_path):
    found = discovery(CodexAdapter(Settings(database_url='sqlite://', codex_executable=str(tmp_path / 'missing'))))
    assert found['status'] == 'Needs Setup'
    assert found['executable'] is None


def test_world_writable_cli_is_rejected(tmp_path):
    runner = local_runner(tmp_path)
    runner.chmod(0o777)
    found = discovery(CodexAdapter(Settings(database_url='sqlite://', codex_executable=str(runner))))
    assert found['status'] == 'Needs Setup'
    assert found['executable'] is None


@pytest.mark.parametrize('fault,expected', [('auth', 'AUTHENTICATION_REQUIRED'),
    ('network', 'PROVIDER_UNREACHABLE'), ('model', 'MODEL_UNAVAILABLE'), ('secret', 'PROVIDER_UNREACHABLE')])
def test_readiness_failure_classes_are_distinct_and_secret_free(tmp_path, fault, expected, caplog):
    repo, runner, verifier = environment(tmp_path, fault=fault)
    with make_client(tmp_path, repo, runner, local_verification_command=verifier) as client:
        init_and_login(client)
        response = client.post('/api/guided-tool-setup/check', json=CHOICE)
        assert response.status_code == 200, response.text
        config = response.json()['configuration']
        assert config['status'] == expected, response.text
        assert config['ready'] is False
        assert client.post('/api/guided-tool-setup/save', json={'configuration_id': config['id']}).status_code == 409
        assert 'sk-fixture-secret' not in response.text + caplog.text
        assert counts(client) == dict.fromkeys(counts(client), 0)


@pytest.mark.parametrize('patch', [{'model_identifier': 'missing-model'}, {'model_identifier': 'gpt-6-astra; sh'},
    {'reasoning_effort': 'invented'}, {'reasoning_effort': 'ultra'}, {'shell_command': 'echo unsafe'},
    {'executable': '/bin/sh'}, {'api_key': 'never-store-me'}])
def test_invalid_configuration_never_falls_back_or_accepts_commands(tmp_path, patch):
    repo, runner, verifier = environment(tmp_path)
    with make_client(tmp_path, repo, runner, local_verification_command=verifier) as client:
        init_and_login(client)
        response = client.post('/api/guided-tool-setup/check', json={**CHOICE, **patch})
        assert response.status_code in {409, 422}, response.text
        assert not runner.with_name(runner.name + '.probe-executed').exists()
        assert counts(client)['codex_runs'] == 0


def test_explicit_readiness_save_restart_and_configuration_drift(tmp_path):
    repo, runner, verifier = environment(tmp_path)
    with make_client(tmp_path, repo, runner, timeout=20, local_verification_command=verifier) as client:
        init_and_login(client)
        task = create_task(client)
        for _ in range(2):
            setup = client.get('/api/guided-tool-setup').json()
            assert setup['configuration'] is None
            assert setup['provider_request_performed'] is False
            assert client.get(f'/api/tasks/{task}/first-delivery').json()['stage'] == 'Tool Setup'
        assert not runner.with_name(runner.name + '.probe-executed').exists()
        config = check_and_save(client)
        assert counts(client)['codex_instruction_packs'] == 0
        prepared = client.post(f'/api/tasks/{task}/first-delivery/prepare')
        assert prepared.status_code == 200, prepared.text
        pack = prepared.json()
        assert client.post(f'/api/tasks/{task}/first-delivery/prepare').json()['id'] == pack['id']
        assert counts(client)['codex_runs'] == 0
        assert start_codex_run(client, {}, task, pack).status_code == 409
        approve_pack(client, {}, task, pack['id'])
        with client.app.state.session_factory() as session:
            frozen = session.get(CodexInstructionPack, pack['id']).content
            binding = pack_binding(session.get(CodexInstructionPack, pack['id']))
            assert binding['snapshot']['reasoning_effort'] == 'xhigh'
        check_and_save(client, {**CHOICE, 'reasoning_effort': 'max'})
        assert client.get(f'/api/tasks/{task}/run-eligibility').json()['eligible'] is False
        assert start_codex_run(client, {}, task, pack).status_code == 409
        with client.app.state.session_factory() as session:
            assert session.get(CodexInstructionPack, pack['id']).content == frozen
        assert counts(client)['codex_runs'] == 0
    with make_client(tmp_path, repo, runner, timeout=20, local_verification_command=verifier) as client:
        init_and_login(client)
        saved = client.get('/api/guided-tool-setup').json()['configuration']
        assert saved['confirmed'] is True and saved['reasoning_effort'] == 'max'
        assert client.get(f'/api/tasks/{task}/first-delivery').json()['stage'] == 'Task Ready'


def test_cross_owner_and_cross_task_access_denied(tmp_path):
    repo, runner, verifier = environment(tmp_path)
    with make_client(tmp_path, repo, runner, local_verification_command=verifier) as client:
        init_and_login(client)
        task = create_task(client)
        other_task = create_task(client, 'Another task')
        check_and_save(client)
        pack = client.post(f'/api/tasks/{task}/first-delivery/prepare').json()
        assert client.post(f"/api/tasks/{other_task}/codex-packs/{pack['id']}/approve").status_code == 404
        client.post('/api/auth/logout')
        # Reuse the accepted 19.1C/19.1D account-isolation fixture path.
        # First Owner creation remains one-time; this is not a signup flow.
        password_hash, password_salt = hash_password('other-owner-password-19-2b')
        token = 'vol19-guided-delivery-other-owner-test-session'
        with client.app.state.session_factory() as session:
            other = User(username='other-owner-19-2b', password_hash=password_hash,
                         password_salt=password_salt, is_active=True)
            session.add(other)
            session.flush()
            session.add(SessionToken(user_id=other.id, token_hash=hash_token(token),
                                     expires_at=utc_now() + timedelta(hours=1)))
            session.commit()
        client.headers['Authorization'] = f'Bearer {token}'
        assert client.get('/api/guided-tool-setup').status_code == 403
        assert client.post('/api/guided-tool-setup/check', json=CHOICE).status_code == 403
        assert client.post(f'/api/tasks/{task}/first-delivery/prepare').status_code == 404
        assert client.get(f'/api/tasks/{task}/codex-packs').status_code == 404
        for alternate in (f'+{task}', f'%20{task}%20', f'{task:04d}'):
            assert client.patch(f'/api/tasks/{alternate}', json={'title': 'Forbidden'}).status_code == 404
            assert client.get(f'/api/tasks/{alternate}/codex-packs').status_code == 404
            assert client.get(f'/api/tasks/{alternate}/codex-runs').json() == []
        assert client.get('/api/codex/status', params={'task_id': f'+{task}'}).status_code == 404
        assert client.post('/api/ai/team-compose', json={'task_id': task}).status_code == 404
        assert client.get('/api/tasks').json() == []


def test_complete_first_safe_delivery_uses_public_actions_and_exact_local_remote(tmp_path):
    repo, runner, verifier = environment(tmp_path)
    origin = tmp_path / 'origin.git'
    run_command(tmp_path, 'git', 'init', '--bare', '--initial-branch=main', str(origin))
    git(repo, 'remote', 'add', 'origin', str(origin))
    git(repo, 'push', '--set-upstream', 'origin', 'HEAD:refs/heads/main')
    baseline = git(repo, 'rev-parse', 'HEAD')
    def remote_sha():
        return git(tmp_path, '--git-dir', str(origin), 'rev-parse', 'refs/heads/main')
    with make_client(tmp_path, repo, runner, timeout=30, local_verification_command=verifier) as client:
        init_and_login(client)
        task = create_task(client)
        assert counts(client) == dict.fromkeys(counts(client), 0)
        check_and_save(client)
        response = client.post(f'/api/tasks/{task}/first-delivery/prepare')
        assert response.status_code == 200, response.text
        pack = response.json()
        assert counts(client)['codex_runs'] == 0
        assert client.get(f'/api/tasks/{task}/first-delivery').json()['stage'] == 'Pack Ready'
        approve_pack(client, {}, task, pack['id'])
        assert client.get(f'/api/tasks/{task}/first-delivery').json()['stage'] == 'Pack Approved'
        assert client.post(f'/api/tasks/{task}/codex-runs', json={}).status_code == 422
        started = start_codex_run(client, {}, task, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()['id']
        terminal = wait_for_run(client, {}, run_id, {"completed", "failed", "timed_out", "cancelled", "integrity_blocked"}, timeout=60)
        assert terminal['status'] == 'completed', terminal
        # Run completion precedes sealed phase publication and Result intake.
        # Use the accepted 19.1 settlement boundary before asserting final truth.
        envelope = _result_envelope(client, {}, run_id)
        terminal = client.get(f'/api/codex-runs/{run_id}').json()
        assert terminal['terminal_truth']['verification']['status'] == 'passed', terminal
        assert terminal['terminal_truth'] == envelope['terminal_truth']
        assert envelope['result']['verification_result']['verdict'] == 'PASS'
        assert terminal['result']['verification']['semantic_verification_passed'] is True
        assert terminal['result']['verification_invocation']['process_execution_verified'] is True
        assert terminal['result']['verification_invocation']['model_provider_invoked'] is False
        assert runner.with_suffix('.reasoning').read_text() == 'model_reasoning_effort="xhigh"'
        assert counts(client)['codex_runs'] == 1
        assert counts(client)['apply_sessions'] == 0
        assert (repo / 'first_delivery.txt').read_text() == BEFORE
        candidate = client.get(f'/api/codex-runs/{run_id}/delivery-candidate').json()['candidate']
        accepted = client.post(f'/api/codex-runs/{run_id}/delivery-review/accept', json=_decision_payload(
            envelope, candidate, confirmation='ACCEPT_RESULT_FOR_DELIVERY', note='Accept independently verified exact content.'))
        assert accepted.status_code == 200, accepted.text
        decision = accepted.json()['review']['advanced']['decision_digest']
        plan_response = client.post(f'/api/codex-runs/{run_id}/apply-plans')
        assert plan_response.status_code == 200, plan_response.text
        plan = plan_response.json()['plan']
        approved = client.post(f"/api/apply-plans/{plan['id']}/approve", json={
            'confirmation': 'APPROVE_APPLY_PLAN', 'expected_plan_digest': plan['advanced']['plan_digest'],
            'expected_candidate_digest': plan['advanced']['candidate_digest'], 'expected_result_digest': plan['advanced']['result_digest'],
            'expected_result_review_decision_digest': decision})
        assert approved.status_code == 200, approved.text
        assert (repo / 'first_delivery.txt').read_text() == BEFORE
        url = f"/api/apply-plans/{plan['id']}/apply-sessions"
        confirmation = client.get(url).json()['apply_confirmation']
        applied = client.post(url, json={'confirmation': 'APPLY_ACCEPTED_CHANGES', **{key: value for key, value in confirmation.items() if key.startswith('expected_')}})
        assert applied.status_code == 200, applied.text
        applied = applied.json()['session']
        assert (repo / 'first_delivery.txt').read_text() == AFTER
        assert git(repo, 'rev-parse', 'HEAD') == baseline
        assert remote_sha() == baseline
        assert counts(client)['local_commit_executions'] == 0
        checked = client.post(f"/api/apply-sessions/{applied['id']}/post-apply-verifications", json={'expected_journal_digest': applied['journal_digest']})
        assert checked.status_code == 200, checked.text
        verification = checked.json()['verification']
        assert verification['status'] == 'PASSED'
        proposal_response = client.post(f"/api/post-apply-verifications/{verification['id']}/commit-proposals", json={
            'expected_verification_digest': verification['advanced']['verification_digest'], 'subject': 'feat: first safe delivery', 'body': 'Deliver the exact approved file.'})
        assert proposal_response.status_code == 200, proposal_response.text
        proposal = proposal_response.json()['proposal']
        approved = client.post(f"/api/commit-proposals/{proposal['id']}/approvals", json={
            'confirmation': 'APPROVE_COMMIT_PROPOSAL', 'expected_proposal_digest': proposal['proposal_digest'], 'expected_proposal_version': proposal['version']})
        assert approved.status_code == 200, approved.text
        approval = approved.json()['proposal']['approval']
        assert git(repo, 'rev-parse', 'HEAD') == baseline
        committed = client.post(f"/api/commit-proposals/{proposal['id']}/local-commits", json={
            'confirmation': 'CREATE_LOCAL_COMMIT', 'expected_proposal_digest': proposal['proposal_digest'], 'expected_approval_digest': approval['approval_digest']})
        assert committed.status_code == 200, committed.text
        commit = committed.json()['proposal']['commit']
        assert commit['state'] == 'COMMITTED'
        assert counts(client)['push_executions'] == 0
        assert remote_sha() == baseline
        reviewed = client.post(f"/api/local-commits/{commit['id']}/push-plans", json={})
        assert reviewed.status_code == 200, reviewed.text
        push_plan = reviewed.json()['push_plan']
        assert push_plan['remote'] == 'origin' and push_plan['target_ref'] == 'refs/heads/main'
        assert push_plan['no_force'] and push_plan['no_tags']
        assert push_plan['refspec'] == commit['commit_oid'] + ':refs/heads/main'
        approved = client.post(f"/api/push-plans/{push_plan['id']}/approvals", json={
            'confirmation': 'APPROVE_PUSH_PLAN', 'expected_plan_digest': push_plan['advanced']['plan_digest'], 'expected_plan_version': push_plan['version']})
        assert approved.status_code == 200, approved.text
        assert remote_sha() == baseline
        pushed = client.post(f"/api/push-plans/{push_plan['id']}/push-attempts", json={
            'confirmation': 'PUSH_TO_ORIGIN_MAIN', 'expected_plan_digest': push_plan['advanced']['plan_digest'],
            'expected_approval_digest': approved.json()['push_approval']['advanced']['approval_digest']})
        assert pushed.status_code == 200, pushed.text
        assert pushed.json()['delivery_result']['verified_remote_sha'] == remote_sha() == commit['commit_oid']
        assert git(tmp_path, '--git-dir', str(origin), 'for-each-ref', '--format=%(refname)') == 'refs/heads/main'
        assert git(tmp_path, '--git-dir', str(origin), 'show', 'main:first_delivery.txt') == AFTER.strip()
        final_counts = counts(client)
        assert final_counts == {key: 1 for key in final_counts}
        for _ in range(2):
            progress = client.get(f'/api/tasks/{task}/first-delivery')
            assert progress.status_code == 200, progress.text
            assert progress.json()['stage'] == 'Delivered', progress.text
            assert counts(client) == final_counts
    with make_client(tmp_path, repo, runner, timeout=30, local_verification_command=verifier) as client:
        init_and_login(client)
        progress = client.get(f'/api/tasks/{task}/first-delivery')
        assert progress.status_code == 200, progress.text
        assert progress.json()['stage'] == 'Delivered'
        assert counts(client) == final_counts
        assert remote_sha() == commit['commit_oid']
        regenerated = client.post(f'/api/tasks/{task}/first-delivery/prepare')
        assert regenerated.status_code == 200, regenerated.text
        assert regenerated.json()['id'] != pack['id']
        assert client.get(f'/api/tasks/{task}/first-delivery').json()['stage'] == 'Pack Ready'
        approve_pack(client, {}, task, regenerated.json()['id'])
        assert client.get(f'/api/tasks/{task}/first-delivery').json()['stage'] == 'Pack Approved'
        assert counts(client)['codex_runs'] == 1


def test_guided_ui_uses_only_explicit_readiness_and_one_current_action():
    root = Path(__file__).resolve().parents[1] / 'static_cockpit/vol12_static_mvp'
    js = (root / 'twos_command_center.js').read_text()
    opening = js.split('async function openGuidedToolSetup()', 1)[1].split('async function checkGuidedTool()', 1)[0]
    assert '/api/guided-tool-setup/check' not in opening
    assert '/api/model-catalog' not in opening
    assert '/api/guided-tool-setup' in opening
    html = (root / 'twos_command_center.html').read_text()
    assert html.count('id="first-delivery-action"') == 1
    assert 'Advanced — full Pack' in html
    assert 'overflow-wrap: anywhere' in (root / 'styles.css').read_text()


@pytest.mark.parametrize('readiness,passive,authenticated,ready,expected', [
    ('Skipped', True, False, False, 'Codex: Skipped'),
    ('Not checked', True, False, False, 'Codex: Not checked'),
    ('Needs setup', True, False, False, 'Codex: Needs setup'),
    ('Ready', False, True, True, 'Codex: Tool ready — check Task readiness below'),
])
def test_codex_header_display_states(readiness, passive, authenticated, ready, expected):
    import subprocess
    source = (Path(__file__).resolve().parents[1] / 'static_cockpit/vol12_static_mvp/twos_command_center.js').read_text()
    render = 'function renderHeaderStatus()' + source.split(
        'function renderHeaderStatus()', 1)[1].split('function renderProjectOptions()', 1)[0]
    label = 'function connectivityStateLabel(value)' + source.split(
        'function connectivityStateLabel(value)', 1)[1].split('function connectivityBoolean', 1)[0]
    detection = {'readiness_state': readiness, 'passive': passive,
                 'authentication_ready': authenticated, 'execution_ready': ready,
                 'connectivity': {'ready_for_real_run': ready,
                     'readiness_state': 'READY_FOR_REAL_RUN' if ready else 'AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED'}}
    harness = '''
const state = {codexStatus: DETECTION};
const elements = {codexHeaderStatus: {dataset: {}}, accountUsername: {}, runtimeHealth: {}};
function objectRecord(value) { return value && typeof value === 'object' ? value : {}; }
globalThis.fetch = () => { throw new Error('Header rendering must remain passive'); };
'''.replace('DETECTION', json.dumps(detection)) + label + render + '''
renderHeaderStatus();
process.stdout.write(JSON.stringify(elements.codexHeaderStatus));
'''
    result = subprocess.run(['node', '-e', harness], check=True, capture_output=True, text=True)
    header = json.loads(result.stdout)
    assert header['textContent'] == expected
    assert header['dataset']['status'] == ('ready' if ready else 'setup')


def test_selecting_an_available_model_reenables_only_the_explicit_check():
    import subprocess
    source = (Path(__file__).resolve().parents[1] / 'static_cockpit/vol12_static_mvp/twos_command_center.js').read_text()
    function = 'function guidedToolSelectionsChanged()' + source.split(
        'function guidedToolSelectionsChanged()', 1)[1].split('function populateGuidedEfforts', 1)[0]
    harness = '''
const state = {guidedToolDiscovery: {status: 'Not checked'}, guidedToolChecked: {ready: true}};
const nodes = {'guided-tool-save': {disabled: false}, 'guided-tool-check': {disabled: true},
  'guided-model': {value: 'gpt-6-astra'}, 'guided-effort': {value: 'xhigh'}, 'guided-tool-state': {},
  'guided-auth': {}, 'guided-tool-close': {}};
function byId(id) { return nodes[id]; }
''' + function + '''
guidedToolSelectionsChanged();
if (nodes['guided-tool-check'].disabled || !nodes['guided-tool-save'].disabled || state.guidedToolChecked !== null) process.exit(1);
nodes['guided-model'].value = '';
guidedToolSelectionsChanged();
if (!nodes['guided-tool-check'].disabled) process.exit(2);
'''
    subprocess.run(['node', '-e', harness], check=True)


def test_guided_stage_and_action_never_cross_task_or_run_selection():
    import subprocess
    source = (Path(__file__).resolve().parents[1] / 'static_cockpit/vol12_static_mvp/twos_command_center.js').read_text()
    render = 'function renderFirstDeliveryGuide()' + source.split(
        'function renderFirstDeliveryGuide()', 1)[1].split('function guidedToolSelectionsChanged', 1)[0]
    action = 'async function firstDeliveryAction()' + source.split(
        'async function firstDeliveryAction()', 1)[1].split('function bindEvents', 1)[0]
    harness = '''
let task = {id: 2};
let run = null;
let calls = 0;
const state = {pending: new Set(), firstDeliveryGuide: {task_id: 1, stage_index: 1, stage: 'Task Ready',
  stages: ['Tool Setup', 'Task Ready'], next_action: 'prepare', action_label: 'Prepare First Delivery'}};
const nodes = {};
function byId(id) { return nodes[id] ||= {replaceChildren() {}, appendChild() {}}; }
function selectedTask() { return task; }
function currentCodexRun() { return run; }
function performAction() { calls += 1; }
function approveApplyPlan() { calls += 1; }
const document = {createElement() { return {setAttribute() {}}; }};
''' + render + action + '''
(async () => {
  for (const selection of [{id: 2}, null]) {
    task = selection;
    renderFirstDeliveryGuide();
    await firstDeliveryAction();
    if (!nodes['first-delivery-guide'].hidden || calls !== 0) process.exit(1);
  }
  task = {id: 1};
  renderFirstDeliveryGuide();
  await firstDeliveryAction();
  if (nodes['first-delivery-guide'].hidden || calls !== 1) process.exit(2);
  Object.assign(state.firstDeliveryGuide, {stage_index: 7, run_id: 20, next_action: 'approve_apply_plan'});
  for (const selection of [{id: 19}, null]) {
    run = selection;
    renderFirstDeliveryGuide();
    await firstDeliveryAction();
    if (!nodes['first-delivery-guide'].hidden || calls !== 1) process.exit(3);
  }
  run = {id: 20};
  renderFirstDeliveryGuide();
  await firstDeliveryAction();
  if (nodes['first-delivery-guide'].hidden || calls !== 2) process.exit(4);
})();
'''
    subprocess.run(['node', '-e', harness], check=True)


def test_guided_schema_and_immutable_configuration_persist_after_restart(tmp_path):
    repo, runner, verifier = environment(tmp_path)
    with make_client(tmp_path, repo, runner, local_verification_command=verifier) as client:
        init_and_login(client)
        task = create_task(client)
        config = check_and_save(client)
        with client.app.state.session_factory() as session:
            versions = set(session.execute(text('SELECT version FROM schema_versions')).scalars())
            assert 'vol19.004' in versions and 'vol19.005' in versions
        statements = [
            "UPDATE guided_tool_configurations SET snapshot_json = '{}'",
            "UPDATE guided_tool_configurations SET owner_id = owner_id + 1",
            "UPDATE guided_tool_configurations SET model_id = model_id + 1",
            "UPDATE guided_tool_configurations SET configuration_digest = 'changed'",
            "UPDATE guided_tool_configurations SET confirmed_at = NULL",
            "DELETE FROM guided_tool_configurations",
            "UPDATE tasks SET owner_user_id = NULL",
        ]
        for statement in statements:
            with client.app.state.session_factory() as session:
                with pytest.raises(IntegrityError, match='immutable'):
                    session.execute(text(statement))
                session.rollback()
        assert counts(client)['codex_runs'] == 0
    with make_client(tmp_path, repo, runner, local_verification_command=verifier) as client:
        init_and_login(client)
        persisted = client.get('/api/guided-tool-setup').json()['configuration']
        assert persisted['id'] == config['id'] and persisted['ready'] and persisted['confirmed']
        assert client.get(f'/api/tasks/{task}/first-delivery').json()['stage'] == 'Task Ready'


def test_first_run_to_guided_setup_and_approved_pack_uses_canonical_paths(tmp_path):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from twos_runtime.app import create_app
    from tests.test_vol19_fresh_install_first_run import (
        fresh_settings, create_owner_and_workspace, finish_setup, USERNAME, PASSWORD,
    )
    repo, runner, verifier = environment(tmp_path)
    settings = replace(fresh_settings(tmp_path), codex_executable=str(runner),
                       local_verification_command=verifier)
    app = create_app(settings, start_scheduler=False)
    try:
        with TestClient(app) as client:
            create_owner_and_workspace(client, settings, repo)
            finish_setup(client)
            task = create_task(client)
            for _ in range(2):
                assert client.get('/api/guided-tool-setup').json()['configuration'] is None
                assert client.get(f'/api/tasks/{task}/first-delivery').json()['stage'] == 'Tool Setup'
                assert client.get('/api/codex/status').json()['passive'] is True
            with app.state.session_factory() as session:
                assert session.execute(text('SELECT count(*) FROM codex_connectivity_evidence')).scalar_one() == 0
            check_and_save(client)
            pack = client.post(f'/api/tasks/{task}/first-delivery/prepare')
            assert pack.status_code == 200, pack.text
            assert pack.json()['generation_metadata']['guided_delivery']['snapshot']['workspace'] == str(repo.resolve())
            approve_pack(client, {}, task, pack.json()['id'])
            eligibility = client.get(f'/api/tasks/{task}/run-eligibility')
            assert eligibility.json()['eligible'] is True, eligibility.text
            assert counts(client)['codex_runs'] == 0
    finally:
        app.state.engine.dispose()
    restarted = create_app(settings, start_scheduler=False)
    try:
        with TestClient(restarted) as client:
            assert client.post('/api/auth/login', json={'username': USERNAME, 'password': PASSWORD}).status_code == 200
            assert client.get('/api/setup/status').json()['state'] == 'ready'
            assert client.get(f'/api/tasks/{task}/first-delivery').json()['stage'] == 'Pack Approved'
            eligibility = client.get(f'/api/tasks/{task}/run-eligibility')
            assert eligibility.json()['eligible'] is True, eligibility.text
            assert counts(client)['codex_runs'] == 0
    finally:
        restarted.state.engine.dispose()


@pytest.mark.parametrize('width', [1280, 390])
@pytest.mark.parametrize('surface', ['guide', 'tool_dialog', 'pack_dialog'])
def test_guided_geometry_uses_real_browser(tmp_path, monkeypatch, width, surface):
    import tests.test_vol19_fresh_install_first_run_ui as layout
    original = layout._geometry_fixture
    def fixture(_):
        page = original('first_task')
        target = {'guide': 'first-delivery-guide', 'tool_dialog': 'guided-tool-dialog', 'pack_dialog': 'guided-pack-dialog'}[surface]
        page = page.replace('const root = document.querySelector("#task-card")', f'const root = document.querySelector("#{target}")')
        setup = '''<script>
        document.getElementById('first-delivery-guide').hidden = false;
        document.getElementById('first-delivery-message').textContent = 'Review the exact requested model and your current next action.';
        document.getElementById('first-delivery-stages').innerHTML = ['Tool Setup','Task Ready','Pack Ready','Pack Approved','Run','Verification','Result Review','Apply','Commit','Push','Delivered'].map(x => '<li>'+x+'</li>').join('');
        document.getElementById('guided-executable').textContent = '/local/' + 'very-long-safe-executable-path-'.repeat(16);
        document.getElementById('guided-version').textContent = 'codex-cli 0.153.4';
        document.getElementById('guided-model').innerHTML = '<option>gpt-6-astra-with-a-very-long-model-name</option>';
        document.getElementById('guided-pack-summary').textContent = 'Review Task, workspace, source snapshot, model and exact Verification before approval.';
        </script>'''
        if surface != 'guide':
            setup += f'<script>document.getElementById("{target}").showModal();</script>'
        return page.replace('<script>\n(() => {\n  const root', setup + '<script>\n(() => {\n  const root', 1)
    monkeypatch.setattr(layout, '_geometry_fixture', fixture)
    geometry = layout._browser_geometry(tmp_path, surface='first_task', width=width)
    assert geometry['innerWidth'] == width
    assert geometry['documentScrollWidth'] <= width
    assert geometry['rootRight'] <= width + 1
    assert geometry['rootLeft'] >= -1
    assert geometry['overflow'] == []


@pytest.mark.parametrize('drift', ['verifier', 'executable', 'context'])
def test_material_runtime_drift_blocks_ready_and_pack_approval(tmp_path, monkeypatch, drift):
    repo, runner, verifier = environment(tmp_path)
    with make_client(tmp_path, repo, runner, local_verification_command=verifier) as client:
        init_and_login(client)
        task = create_task(client)
        check_and_save(client)
        prepared = client.post(f'/api/tasks/{task}/first-delivery/prepare')
        assert prepared.status_code == 200, prepared.text
        pack = prepared.json()
        if drift == 'context':
            monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:9')
        else:
            path = Path(verifier[1]) if drift == 'verifier' else runner
            path.write_text(path.read_text() + '\n# material configuration replacement\n')
        config = client.get('/api/guided-tool-setup').json()['configuration']
        assert config['ready'] is False
        assert config['status'] == 'Needs Setup'
        if drift != 'context':
            assert client.post(f"/api/tasks/{task}/codex-packs/{pack['id']}/approve").status_code == 409
        assert counts(client)['codex_runs'] == 0
