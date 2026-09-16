from __future__ import annotations

from pathlib import Path
import json
import os

import pytest
from sqlalchemy import select

from tests.test_vol19_guided_acceptance_corrections import commit_ui, function, node
from tests.test_vol19_owner_commit_push_delivery import (
    _canonical_applied_delivery, _create_proposal, _approve_proposal, _confirm_commit, _git,
)
from twos_runtime.models import PostApplyVerification, CommitProposal, LocalCommitExecution
from twos_runtime.owner_commit_delivery import owner_commit_review


@pytest.fixture(autouse=True)
def clear_inherited_git_overrides(monkeypatch):
    for name in tuple(os.environ):
        if name.startswith('GIT_'):
            monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize('state,review_required,ready', [
    ('none', True, True), ('READY', False, False), ('READY', True, True),
    ('EXPIRED', True, True),
])
def test_review_button_completed_and_material_invalidation(state, review_required, ready):
    proposal = {} if state == 'none' else {'id': 'proposal', 'status': state,
        'subject': 'subject', 'body': '', 'actions': {'can_edit': True, 'can_approve': not review_required}}
    output = commit_ui({'run_id': 1, 'delivery_contract': 'VOL19_19_1D',
        'apply_session': {'session': {'state': 'APPLIED'}},
        'post_apply_verification': {'verification': {'id': 'verify', 'status': 'PASSED'}},
        'commit_delivery': {'proposal': proposal, 'review_required': review_required,
            'actions': {'can_review_commit': review_required}}})
    button = output['elements']['reviewOwnerCommit']
    assert button['disabled'] is not ready
    assert button['className'] == ('button button-primary' if ready else 'button button-quiet')
    assert button['textContent'] == ('Review Commit' if ready else 'Review completed')
    assert output['elements']['confirmOwnerLocalCommit']['disabled'] is True


def test_review_pending_duplicate_guard_and_completed_action_is_noop():
    source = Path('static_cockpit/vol12_static_mvp/twos_command_center.js').read_text()
    action = function('performAction')
    assert 'state.pending.has(key)' in action
    assert 'state.pending.add(key)' in action
    assert 'state.pending.delete(key)' in action
    assert 'state.pending.has("review-owner-commit")' in function('renderOwnerCommitPushDelivery')
    harness = '''
const elements={reviewOwnerCommit:{},commitPlanSubject:{value:'subject'},commitPlanBody:{value:''}};
const context={parts:{proposal:{subject:'subject',body:''},commitDelivery:{review_required:false},commitActions:{}}};
function ownerDeliveryActionContext(){return context;}
async function performAction(k,b,l,fn){await fn();}
async function api(){throw new Error('Completed review must not submit');}
'''
    node(harness + function('reviewOwnerCommit') + '\nreviewOwnerCommit().catch(e=>{console.error(e);process.exitCode=1;});')


@pytest.mark.parametrize('change', ['author', 'source', 'approved_paths', 'verification', 'apply'])
def test_review_freshness_reacts_and_commit_guards_remain(tmp_path, change):
    with _canonical_applied_delivery(tmp_path) as fixture:
        response = _create_proposal(fixture)
        assert response.status_code == 200, response.text
        proposal = response.json()['proposal']
        def review():
            with fixture.factory() as session:
                verification = session.scalar(select(PostApplyVerification).where(
                    PostApplyVerification.verification_id == fixture.verification['id']))
                return owner_commit_review(session, owner_id=verification.owner_id,
                    post_apply_verification=verification, source_repo=fixture.source_repo)
        initial = review()
        assert initial['review_required'] is False
        assert initial['proposal']['actions']['can_approve'] is True
        approval = _approve_proposal(fixture, proposal).json()['proposal']['approval']
        if change == 'author':
            _git(fixture.source_repo, 'config', 'user.name', 'Changed Author')
            stale = review()
            assert stale['review_required'] is True
            assert stale['actions']['can_review_commit'] is True
            assert stale['proposal']['actions']['can_commit'] is False
            replacement = _create_proposal(fixture).json()['proposal']
            assert replacement['id'] != proposal['id']
            assert replacement['approval'] is None
        elif change == 'source':
            path = proposal['files'][0]['path']
            (fixture.source_repo / path).write_text('material drift\n')
            assert review()['review_required'] is True
        elif change in {'approved_paths', 'verification'}:
            # These upstream records are immutable by contract. An attempted
            # in-place change must be rejected, never silently retain authority.
            from sqlalchemy.exc import DBAPIError
            with fixture.factory() as session:
                if change == 'approved_paths':
                    row = session.scalar(select(CommitProposal).where(CommitProposal.proposal_id == proposal['id']))
                    row.planned_paths_digest = 'changed'
                else:
                    row = session.scalar(select(PostApplyVerification).where(
                        PostApplyVerification.verification_id == fixture.verification['id']))
                    row.verification_digest = 'changed'
                with pytest.raises(RuntimeError, match="append-only and immutable"):
                    session.commit()
                session.rollback()
            assert review()['review_required'] is False
            with fixture.factory() as session:
                assert session.scalar(select(LocalCommitExecution)) is None
            return
        else:
            from twos_runtime.models import ApplySession
            with fixture.factory() as session:
                verification = session.scalar(select(PostApplyVerification).where(
                    PostApplyVerification.verification_id == fixture.verification['id']))
                session.get(ApplySession, verification.apply_session_id).state = 'REVERTED'
                session.commit()
            try:
                assert review()['review_required'] is True
            except Exception as exc:
                from twos_runtime.commit_builder import CommitBuilderError
                assert isinstance(exc, CommitBuilderError)
        refused = _confirm_commit(fixture, proposal, approval)
        assert refused.status_code in {400, 409}
        with fixture.factory() as session:
            assert session.scalar(select(LocalCommitExecution)) is None


def test_maintenance_minimal_discoverability_preserves_single_action():
    page = Path('static_cockpit/maintenance.html').read_text()
    assert 'aria-describedby="operation-help"' in page
    assert 'Choose one maintenance action from this menu.' in page
    assert page.count('id="primary"') == 1
    assert page.count('id="operation"') == 1
    guide = Path('docs/OWNER_GUIDE.md').read_text()
    for action in ('Create a backup', 'Inspect and restore a backup', 'Migrate an older', 'Reauthorize workspace'):
        assert action in guide


def test_commit_owner_text_is_rendered_as_text_without_execution():
    hostile = '<img src=x onerror="throw 1"> & <script>throw 2</script>'
    output = commit_ui({'run_id': 1, 'delivery_contract': 'VOL19_19_1D',
        'apply_session': {'session': {'state': 'APPLIED'}},
        'post_apply_verification': {'verification': {'id': 'verify', 'status': 'PASSED'}},
        'commit_delivery': {'proposal': {'id': 'proposal', 'status': 'READY', 'subject': hostile,
            'body': hostile, 'actions': {'can_edit': True}}, 'review_required': False}})
    assert output['elements']['commitBuilderSubject']['textContent'] == hostile
    assert output['elements']['commitPlanBody']['value'] == hostile
    for path in ('static_cockpit/maintenance.js', 'static_cockpit/vol12_static_mvp/twos_command_center.js'):
        script = Path(path).read_text()
        assert not any(sink in script for sink in ('innerHTML', 'outerHTML', 'insertAdjacentHTML', 'document.write('))


@pytest.mark.parametrize('body', ['', '  Keep exact body\n\t'])
def test_completed_review_preserves_exact_message_whitespace(body):
    output = commit_ui({'run_id': 1, 'delivery_contract': 'VOL19_19_1D',
        'apply_session': {'session': {'state': 'APPLIED'}},
        'post_apply_verification': {'verification': {'id': 'verify', 'status': 'PASSED'}},
        'commit_delivery': {'proposal': {'id': 'proposal', 'status': 'READY', 'subject': 'Subject',
            'body': body, 'actions': {'can_edit': True}}, 'review_required': False}})
    fields = output['elements']
    assert fields['commitPlanBody']['value'] == body
    assert fields['reviewOwnerCommit']['disabled'] is True
    assert fields['reviewOwnerCommit']['className'] == 'button button-quiet'


@pytest.mark.parametrize('edited,pending', [(False, False), (True, False), (False, True)])
def test_edited_message_availability_requires_review_before_approval_or_commit(edited, pending):
    availability = function('renderActionAvailability')
    # Execute the production canonical-delivery branch, without unrelated Task UI.
    branch = availability.split('    if (canonicalOwnerDeliveryAvailable(codexRun)) {', 1)[1].split(
        '    const decisionPending', 1)[0]
    branch = 'if (canonicalOwnerDeliveryAvailable(codexRun)) {' + branch
    harness = '''
const parts={proposal:{id:'p',subject:'A',body:'',status:'READY'},commitDelivery:{review_required:false},
 commitActions:{can_edit:true,can_approve:true,can_commit:true},pushActions:{}};
const elements=new Proxy({}, {get(t,k){return t[k] ||= {};}});
elements.commitPlanSubject.value=EDITED?'B':'A';elements.commitPlanBody.value='';
const state={pending:new Set(PENDING?['review-owner-commit']:[])};
function objectRecord(v){return v||{};}
function ownerDeliveryParts(){return parts;}
function canonicalOwnerDeliveryAvailable(){return true;}
function canonicalCommitState(){return 'READY';}
function ownerDeliveryRecordId(v){return v.id;}
function ownerPushConfirmationCanConfirm(){return false;}
const authenticated=true,codexRun={id:1};
'''.replace('EDITED', json.dumps(edited)).replace('PENDING', json.dumps(pending))
    result = node(harness + branch + '\nprocess.stdout.write(JSON.stringify(elements));')
    blocked = edited or pending
    assert result['approveCommitProposal']['disabled'] is blocked
    assert result['confirmOwnerLocalCommit']['disabled'] is blocked
    assert result['reviewOwnerCommit']['disabled'] is (not edited or pending)


@pytest.mark.parametrize('action', ['approveOwnerCommitProposal', 'openOwnerLocalCommitConfirmation',
                                   'confirmApprovedLocalCommit'])
def test_unreviewed_message_cannot_submit_approval_or_commit(action):
    harness = '''
const elements={commitPlanSubject:{value:'B'},commitPlanBody:{value:''},
 approveCommitProposal:{},confirmApprovedLocalCommit:{}};
const state={pending:new Set(),ownerCommitConfirmationContext:{proposal_id:'p'}};
function ownerDeliveryActionContext(){return {parts:{proposal:{id:'p',subject:'A',body:''}}};}
class ApiError extends Error{constructor(status,code,message){super(message);this.code=code;}}
async function performAction(k,b,l,fn){await fn();}
let calls=0;
async function api(){calls++;throw new Error('Unreviewed message reached mutation');}
'''
    harness += function('ownerCommitMessageChanged') + function(action)
    result = node(harness + '''
(async()=>{let error=null;try{await ACTION();}catch(e){error=e.code||e.message;}
process.stdout.write(JSON.stringify({calls,error}));})();
'''.replace('ACTION', action))
    assert result['calls'] == 0
    assert result['error'] == (None if action == 'openOwnerLocalCommitConfirmation' else 'COMMIT_REVIEW_REQUIRED')
