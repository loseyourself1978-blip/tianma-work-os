from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from tests.test_vol19_guided_first_delivery import (
    AFTER, BEFORE, CHOICE, approve_pack, check_and_save, counts, create_task,
    environment, git, init_and_login, make_client, start_codex_run, wait_for_run,
    _decision_payload, _result_envelope,
)
from twos_runtime.guided_delivery import delivery_location

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'static_cockpit/vol12_static_mvp/twos_command_center.js').read_text()


@pytest.fixture(autouse=True)
def clean_git_context(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith('GIT_'):
            monkeypatch.delenv(name, raising=False)


def function(name):
    return re.search(r'^  (?:async )?function ' + name + r'\(.*?(?=^  (?:async )?function |\Z)', JS, re.M | re.S)[0]


def node(source):
    result = subprocess.run(['node', '-e', source], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout or '{}')


TOOL_HARNESS = '''
const assert = require('assert/strict');
const state = {guidedToolDiscovery: {status: 'Not checked'}};
const nodes = {};
function byId(id) { return nodes[id] ||= {value: '', textContent: '', disabled: false}; }
byId('guided-model').value = 'gpt-6-astra';
byId('guided-effort').value = 'xhigh';
const checked = {id: 1, model: 'gpt-6-astra', reasoning_effort: 'xhigh', ready: true,
  confirmed: false, status: 'Ready', authentication: 'authenticated',
  last_successful_readiness_check: '2026-09-15T03:00:00Z', next_action: 'Save Tool Setup'};
function productActionMessage(error) { return error.message; }
let calls = 0;
let finish;
async function api(path) {
  assert.equal(path, '/api/guided-tool-setup/check');
  calls += 1;
  return new Promise(resolve => { finish = () => resolve({configuration: checked}); });
}
''' + ''.join(function(name) for name in (
    'guidedToolSelectionsChanged', 'renderGuidedToolControls',
    'showGuidedConfiguration', 'guidedProjectQuery', 'checkGuidedTool'))


@pytest.mark.parametrize('case', ['initial', 'checking', 'success', 'saved', 'unchanged', 'model', 'reasoning', 'identity', 'failure'])
def test_readiness_controls_are_explicit_and_save_is_independent(case):
    node(TOOL_HARNESS + '''
(async () => {
  const scenario = CASE;
  showGuidedConfiguration(null);
  assert.equal(byId('guided-last-check').textContent, 'Never');
  assert.equal(byId('guided-auth').textContent, 'Not checked');
  assert.equal(byId('guided-tool-check').className, 'button button-primary');
  assert.equal(byId('guided-tool-check').disabled, false);
  assert.equal(byId('guided-tool-save').disabled, true);
  assert.equal(calls, 0);
  if (scenario === 'initial') return;
  if (scenario === 'checking' || scenario === 'success') {
    const pending = checkGuidedTool();
    assert.equal(byId('guided-tool-check').disabled, true);
    assert.match(byId('guided-tool-check').textContent, /Checking/);
    assert.equal(byId('guided-tool-save').disabled, true);
    assert.equal(byId('guided-model').disabled, true);
    await checkGuidedTool();
    assert.equal(calls, 1);
    finish(); await pending;
    assert.equal(byId('guided-tool-check').disabled, true);
    assert.equal(byId('guided-tool-check').className, 'button button-quiet');
    assert.equal(byId('guided-tool-save').disabled, false);
    assert.match(byId('guided-tool-state').textContent, /^Ready/);
    assert.equal(byId('guided-last-check').textContent, checked.last_successful_readiness_check);
    await checkGuidedTool(); assert.equal(calls, 1);
    return;
  }
  checked.confirmed = true;
  showGuidedConfiguration(checked);
  assert.equal(byId('guided-tool-save').disabled, true);
  assert.equal(byId('guided-tool-check').disabled, true);
  if (scenario === 'saved' || scenario === 'unchanged') {
    guidedToolSelectionsChanged();
    showGuidedConfiguration(checked); // Passive refresh of saved state.
    assert.equal(byId('guided-tool-save').disabled, true);
    assert.equal(byId('guided-tool-check').disabled, true);
  } else {
    if (scenario === 'model') byId('guided-model').value = 'another-explicit-model';
    if (scenario === 'reasoning') byId('guided-effort').value = 'max';
    if (scenario === 'identity' || scenario === 'failure') {
      showGuidedConfiguration({...checked, ready: false, status: 'Needs Setup'});
    } else guidedToolSelectionsChanged();
    assert.equal(byId('guided-tool-check').disabled, false);
    assert.equal(byId('guided-tool-check').className, 'button button-primary');
    assert.equal(byId('guided-tool-save').disabled, true);
  }
  assert.equal(calls, 0);
})().catch(error => { console.error(error); process.exit(1); });
'''.replace('CASE', json.dumps(case)))


def commit_ui(projection):
    harness = '''
const state = {pending: new Set()};
const projection = PROJECTION;
function objectRecord(value) { return value && typeof value === 'object' ? value : {}; }
function ownerDeliveryProjectionForRun() { return projection; }
const elements = new Proxy({}, {get(target, key) {
  return target[key] ||= {value: '', textContent: '', dataset: {}, disabled: false};
}});
function humanStatus(value) { return value; }
function boundedText(value, fallback) { return value || fallback; }
const sanitizedApplyPlanText = boundedText;
const pushDeliverySummary = boundedText;
function canonicalApprovalState(value, fallback) { return value.status || fallback; }
function canonicalPushState() { return 'PUSH_REVIEW_REQUIRED'; }
function ownerDeliveryPathEntries() { return []; }
function applyPlanTextList(value) { return (value || []).map(item => item.message); }
function ownerPushConfirmationPhaseFor() { return ''; }
function selectedTask() { return {title: 'First delivery'}; }
function setStatusLabel() {}
function appendTextList() {}
function renderCanonicalCommitAdvanced() {}
function renderCommitBuilderFiles() {}
function renderOwnerDeliverySequence() {}
const OWNER_COMMIT_STATE_LABELS = {BLOCKED:'BLOCKED', COMMIT_REVIEW_REQUIRED:'COMMIT_REVIEW_REQUIRED'};
const OWNER_PUSH_STATE_LABELS = {};
globalThis.fetch = () => { throw new Error('Rendering must not execute any action'); };
'''.replace('PROJECTION', json.dumps(projection))
    harness += ''.join(function(name) for name in (
        'ownerDeliveryRecordId', 'ownerDeliveryDigest', 'ownerDeliveryParts',
        'canonicalCommitState', 'canonicalOwnerDeliveryAvailable', 'renderOwnerCommitPushDelivery'))
    return node(harness + '''
renderOwnerCommitPushDelivery({id: 1});
const parts = ownerDeliveryParts({id: 1});
process.stdout.write(JSON.stringify({elements, parts}));
''')


@pytest.mark.parametrize('applied,validated,allowed', [
    ('', '', False), ('PREPARED', 'PASSED', False), ('APPLIED', '', False),
    ('APPLIED', 'FAILED', False), ('APPLIED', 'PASSED', True), ('REVERTED', 'PASSED', False),
])
def test_review_commit_renders_persisted_truth_and_enforces_prerequisites(applied, validated, allowed):
    output = commit_ui({'run_id': 1, 'delivery_contract': 'VOL19_19_1D',
        'apply_session': {'session': {'state': applied}},
        'post_apply_verification': {'verification': {'id': 'pav-1', 'status': validated,
            'advanced': {'verification_digest': 'bound-digest'}}},
        'commit_delivery': {'actions': {'can_create_proposal': True}}})
    fields = output['elements']
    assert fields['ownerCommitApplyState']['textContent'] == (applied or 'Not applied')
    assert fields['ownerCommitPostApplyValidation']['textContent'] == (validated or 'Not verified')
    assert fields['reviewOwnerCommit']['disabled'] is not allowed
    assert output['parts']['postApply']['id'] == 'pav-1'
    assert fields['approveCommitProposal']['disabled'] is True
    assert fields['confirmOwnerLocalCommit']['disabled'] is True
    if not allowed:
        assert 'Return to Apply' in fields['commitBuilderNextAction']['textContent']
        assert 'Validate Applied Changes' in fields['commitBuilderNextAction']['textContent']
        assert 'retry Review Commit' not in fields['commitBuilderNextAction']['textContent']


def test_projection_failure_never_falls_back_to_legacy_commit_or_claims_missing_history():
    output = commit_ui({'run_id': 1, 'delivery_contract': 'VOL19_19_1D',
        'load_error': {'message': 'Connection unavailable'}})
    fields = output['elements']
    assert fields['legacyCommitBuilderControls']['hidden'] is True
    assert fields['ownerCommitApplyState']['textContent'] == 'Unavailable'
    assert fields['ownerCommitPostApplyValidation']['textContent'] == 'Unavailable'
    assert fields['reviewOwnerCommit']['disabled'] is True
    assert 'Reload delivery status' in fields['commitBuilderNextAction']['textContent']


@pytest.mark.parametrize('applied,passed', [(False, False), (True, False), (True, True)])
def test_review_commit_action_requires_both_prerequisites_and_uses_bound_verification(applied, passed):
    projection = {'apply_session': {'session': {'state': 'APPLIED' if applied else 'Not applied'}},
        'post_apply_verification': {'verification': {'id': 'pav-bound', 'status': 'PASSED' if passed else 'FAILED',
            'advanced': {'verification_digest': 'immutable-verification'}}},
        'commit_delivery': {'actions': {'can_create_proposal': True}}}
    harness = '''
const projection = PROJECTION;
const state = {};
const calls = [];
const elements = {reviewOwnerCommit: {}, commitPlanSubject: {value:'feat: delivery'}, commitPlanBody: {value:''}};
function objectRecord(value) { return value && typeof value === 'object' ? value : {}; }
function ownerDeliveryProjectionForRun() { return projection; }
function ownerDeliveryActionContext() { return {parts: ownerDeliveryParts({id:1})}; }
function assertOwnerDeliveryActionCurrent() {}
function validCommitSubject() { return true; }
function validCommitBody() { return true; }
class ApiError extends Error { constructor(status, code, message) { super(message); this.code = code; } }
async function api(url, request) { calls.push({url, request}); }
async function performAction(key, button, label, action) { await action(); }
'''.replace('PROJECTION', json.dumps(projection))
    harness += ''.join(function(name) for name in ('ownerDeliveryParts', 'ownerDeliveryRecordId', 'ownerDeliveryDigest', 'reviewOwnerCommit'))
    output = node(harness + '''
(async () => {
  let error = null;
  try { await reviewOwnerCommit(); } catch (caught) { error = caught.message; }
  process.stdout.write(JSON.stringify({calls, error}));
})();
''')
    if applied and passed:
        assert output['error'] is None
        assert output['calls'] == [{'url': '/api/post-apply-verifications/pav-bound/commit-proposals',
            'request': {'method': 'POST', 'body': {'expected_verification_digest': 'immutable-verification',
                'subject': 'feat: delivery', 'body': ''}}}]
    else:
        assert output['calls'] == []
        assert 'Return to Apply' in output['error']


def test_location_is_current_contained_and_journal_based_after_apply(tmp_path):
    root = tmp_path / 'persistent acceptance/source'
    root.mkdir(parents=True)
    (root / 'escape.txt').symlink_to(tmp_path / 'outside.txt')
    task = SimpleNamespace(implementation_scope='first_delivery.txt only; ../outside.txt /obsolete/source.txt escape.txt')
    settings = SimpleNamespace(source_repo=root)
    location = delivery_location(task, settings)
    assert location['authorized_workspace'] == str(root)
    assert location['source_repository'] == str(root)
    assert location['targets'] == [{'relative_path': 'first_delivery.txt',
        'source_target_path': str(root / 'first_delivery.txt'), 'apply_result': None}]
    result = delivery_location(task, settings, {
        'apply_session': {'session': {'state': 'APPLIED', 'files': [{'path': 'actual.txt', 'apply_result': 'APPLIED'}]}},
        'post_apply_verification': {'verification': {'status': 'PASSED'}}})
    assert result['target_basis'] == 'Apply journal'
    assert result['targets'][0]['source_target_path'] == str(root / 'actual.txt')
    assert result['post_apply_validation'] == 'PASSED'
    assert 'obsolete' not in json.dumps(result)


def test_current_paths_and_applied_evidence_are_rendered_as_copyable_text():
    output = node('''
const state = {pending: new Set(), firstDeliveryGuide: {task_id: 1, run_id: 1, stage_index: 8,
  stage: 'Commit', stages: [], message: 'Review Commit', action_label: 'Review Commit',
  location: {authorized_workspace: '/current/workspace', source_repository: '/current/source',
    targets: [{source_target_path:'/current/source/first_delivery.txt', apply_result:'APPLIED'}],
    target_basis:'Apply journal', apply_state:'APPLIED', post_apply_validation:'PASSED'}}};
const nodes = {};
function byId(id) { return nodes[id] ||= {replaceChildren() {}}; }
function selectedTask() { return {id: 1}; }
function currentCodexRun() { return {id: 1}; }
''' + function('renderFirstDeliveryGuide') + '''
renderFirstDeliveryGuide();
process.stdout.write(JSON.stringify(nodes));
''')
    assert output['first-delivery-workspace']['textContent'] == '/current/workspace'
    assert output['first-delivery-source']['textContent'] == '/current/source'
    assert output['first-delivery-targets']['textContent'] == '/current/source/first_delivery.txt — APPLIED'
    assert output['first-delivery-applied-evidence']['textContent'] == 'Apply: APPLIED. Post-Apply validation: PASSED.'
    html = (ROOT / 'static_cockpit/vol12_static_mvp/twos_command_center.html').read_text()
    assert '<summary>Advanced — workspace, source and target paths</summary>' in html
    assert 'select text to copy' in html
    assert 'twos-v19-19.2b-first-safe-delivery.mge3dcqy' not in html + JS


@pytest.mark.parametrize('width', [1280, 390])
def test_expanded_actual_paths_do_not_block_owner_action(tmp_path, monkeypatch, width):
    import tests.test_vol19_fresh_install_first_run_ui as layout
    original = layout._geometry_fixture
    def fixture(surface):
        page = original(surface)
        setup = '''<script>
        const guide = document.getElementById('first-delivery-guide');
        guide.hidden = false;
        guide.querySelector('details').open = true;
        for (const id of ['first-delivery-workspace','first-delivery-source','first-delivery-targets']) {
          document.getElementById(id).textContent = '/current/' + 'long-workspace-component-'.repeat(30) + '/first_delivery.txt';
        }
        </script>'''
        return page.replace('<script>\n(() => {\n  const root', setup + '<script>\n(() => {\n  const root', 1)
    monkeypatch.setattr(layout, '_geometry_fixture', fixture)
    geometry = layout._browser_geometry(tmp_path, surface='first_task', width=width)
    assert geometry['innerWidth'] == width
    assert geometry['documentScrollWidth'] <= width
    assert geometry['overflow'] == []


def test_unchanged_explicit_recheck_preserves_saved_configuration_without_another_save(tmp_path):
    repo, runner, verifier = environment(tmp_path)
    with make_client(tmp_path, repo, runner, local_verification_command=verifier) as client:
        init_and_login(client)
        check_and_save(client)
        response = client.post('/api/guided-tool-setup/check', json=CHOICE)
        assert response.status_code == 200, response.text
        config = response.json()['configuration']
        assert config['ready'] and config['confirmed']
        assert config['next_action'] == 'Prepare First Delivery'
        changed = client.post('/api/guided-tool-setup/check', json={**CHOICE, 'reasoning_effort': 'max'})
        assert changed.status_code == 200, changed.text
        assert changed.json()['configuration']['confirmed'] is False
        assert changed.json()['configuration']['next_action'] == 'Save Tool Setup'
        assert all(value == 0 for value in counts(client).values())


def test_applied_validation_survives_commit_blocker_refresh_and_restart(tmp_path, monkeypatch):
    repo, runner, verifier = environment(tmp_path)
    baseline = git(repo, 'rev-parse', 'HEAD')
    with make_client(tmp_path, repo, runner, timeout=30, local_verification_command=verifier) as client:
        init_and_login(client)
        task = create_task(client)
        initial = client.get(f'/api/tasks/{task}/first-delivery').json()
        assert initial['location']['targets'][0]['source_target_path'] == str(repo / 'first_delivery.txt')
        check_and_save(client)
        pack = client.post(f'/api/tasks/{task}/first-delivery/prepare').json()
        approve_pack(client, {}, task, pack['id'])
        started = start_codex_run(client, {}, task, pack)
        assert started.status_code == 200, started.text
        run_id = started.json()['id']
        terminal = wait_for_run(client, {}, run_id, {'completed', 'failed'}, timeout=60)
        assert terminal['status'] == 'completed'
        result = _result_envelope(client, {}, run_id)
        assert result['result']['verification_result']['verdict'] == 'PASS'
        candidate = client.get(f'/api/codex-runs/{run_id}/delivery-candidate').json()['candidate']
        accepted = client.post(f'/api/codex-runs/{run_id}/delivery-review/accept', json=_decision_payload(
            result, candidate, confirmation='ACCEPT_RESULT_FOR_DELIVERY', note='Explicit review.'))
        assert accepted.status_code == 200, accepted.text
        plan = client.post(f'/api/codex-runs/{run_id}/apply-plans').json()['plan']
        approved = client.post(f"/api/apply-plans/{plan['id']}/approve", json={
            'confirmation': 'APPROVE_APPLY_PLAN', 'expected_plan_digest': plan['advanced']['plan_digest'],
            'expected_candidate_digest': plan['advanced']['candidate_digest'], 'expected_result_digest': plan['advanced']['result_digest'],
            'expected_result_review_decision_digest': accepted.json()['review']['advanced']['decision_digest']})
        assert approved.status_code == 200, approved.text
        url = f"/api/apply-plans/{plan['id']}/apply-sessions"
        confirmation = client.get(url).json()['apply_confirmation']
        applied = client.post(url, json={'confirmation': 'APPLY_ACCEPTED_CHANGES', **{
            key: value for key, value in confirmation.items() if key.startswith('expected_')}})
        assert applied.status_code == 200, applied.text
        applied = applied.json()['session']
        before_validation = client.get(f'/api/tasks/{task}/first-delivery').json()
        assert before_validation['stage'] == 'Apply'
        assert before_validation['next_action'] == 'validate_applied'
        assert before_validation['delivery']['commit_delivery'] is None
        checked = client.post(f"/api/apply-sessions/{applied['id']}/post-apply-verifications",
            json={'expected_journal_digest': applied['journal_digest']})
        assert checked.status_code == 200, checked.text
        verification = checked.json()['verification']
        assert verification['status'] == 'PASSED'
        for blocked in (True, False):
            with monkeypatch.context() as context:
                if blocked:
                    context.setenv('GIT_PAGER', 'cat') # Actual accepted security guard, no mocked terminal rows.
                for _ in range(2):
                    response = client.get(f'/api/codex-runs/{run_id}/delivery')
                    assert response.status_code == 200, response.text
                    projection = response.json()
                    assert projection['apply_session']['session']['state'] == 'APPLIED'
                    assert projection['post_apply_verification']['verification']['status'] == 'PASSED'
                    assert projection['automatic_actions'] == []
                    output = commit_ui(projection)
                    assert output['elements']['ownerCommitApplyState']['textContent'] == 'APPLIED'
                    assert output['elements']['ownerCommitPostApplyValidation']['textContent'] == 'PASSED'
                    assert output['elements']['reviewOwnerCommit']['disabled'] is blocked
                    if blocked:
                        assert projection['commit_delivery']['blockers'][0]['code'] == 'GIT_ENVIRONMENT_BLOCKED'
                        assert projection['next_action']['primary'] is None
                    guide = client.get(f'/api/tasks/{task}/first-delivery')
                    assert guide.status_code == 200, guide.text
                    assert guide.json()['stage'] == 'Commit'
                    assert guide.json()['location']['post_apply_validation'] == 'PASSED'
        initial_counts = counts(client)
        assert initial_counts['local_commit_executions'] == initial_counts['push_executions'] == 0
        assert (repo / 'first_delivery.txt').read_text() == AFTER
        assert git(repo, 'diff', '--cached', '--name-only') == ''
        assert git(repo, 'rev-parse', 'HEAD') == baseline
    with make_client(tmp_path, repo, runner, timeout=30, local_verification_command=verifier) as client:
        init_and_login(client)
        guide = client.get(f'/api/tasks/{task}/first-delivery').json()
        assert guide['stage'] == 'Commit' and guide['action_label'] == 'Review Commit'
        assert guide['location']['apply_state'] == 'APPLIED'
        assert guide['location']['post_apply_validation'] == 'PASSED'
        assert guide['location']['targets'][0]['source_target_path'] == str(repo / 'first_delivery.txt')
        assert counts(client) == initial_counts
        proposal = client.post(f"/api/post-apply-verifications/{verification['id']}/commit-proposals", json={
            'expected_verification_digest': verification['advanced']['verification_digest'],
            'subject': 'feat: explicitly review delivery', 'body': ''})
        assert proposal.status_code == 200, proposal.text
        assert counts(client) == initial_counts
        with client.app.state.session_factory() as session:
            assert session.execute(text('select count(*) from stage_executions')).scalar_one() == 0
        assert git(repo, 'rev-parse', 'HEAD') == baseline
        assert git(repo, 'diff', '--cached', '--name-only') == ''
