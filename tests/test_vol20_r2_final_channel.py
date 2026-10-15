"""No provider calls: protocol, cleanup durability and fault controls."""
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import tempfile
import errno
import signal
import subprocess
import sys

import pytest
from twos_runtime import execution_evidence as store, project_execution as execution
from tests.test_vol20_r2_response_contract import cli_fixture


def message(text, identity='item_0', phase=None):
    value={'id':identity,'type':'agent_message','text':text}
    if phase is not None:value['phase']=phase
    return {'type':'item.completed','item':value}


def events(messages):
    return [{'type':'thread.started','thread_id':'actual-protocol-no-turn-id'}, {'type':'turn.started'},*messages,{'type':'turn.completed'}]


def extract(tmp_path, values, raw=b'final', **kwargs):
    stream=store.EventStream()
    for event in values:stream.accept(event)
    path=tmp_path/'final';path.write_bytes(raw)
    return stream.extract(path, **kwargs)


@pytest.mark.parametrize('phases',[(None,), (None,None), (None,None,None), ('commentary','final_answer')])
@pytest.mark.parametrize('lf',[False,True])
def test_phase_less_process_messages_are_not_final_answers(tmp_path,phases,lf):
    msgs=[message('{"process":"JSON is not a final discriminator"}',f'item_{i}',p) for i,p in enumerate(phases)]
    msgs[-1]['item']['text']='final'
    raw=b'final'+(b'\n' if lf else b'')
    result,receipt=extract(tmp_path,events(msgs),raw)
    assert result=='final'
    assert receipt['final_result_sha256']==hashlib.sha256(raw).hexdigest()
    assert receipt['final_message_id']==f'item_{len(phases)-1}'


@pytest.mark.parametrize('case,code',[
 ('conflicting_item','RESULT_ITEM_CONFLICT'),('duplicate_terminal','RESULT_TERMINAL_CONFLICT'),
 ('after_terminal','RESULT_TERMINAL_CONFLICT'),('no_turn','RESULT_EVENT_STREAM_INCOMPLETE'),
 ('no_thread','RESULT_EVENT_STREAM_INCOMPLETE'),('commentary_only','RESULT_FINAL_AMBIGUOUS'),
 ('earlier_match','RESULT_FINAL_AMBIGUOUS'),('extra_whitespace','RESULT_FINAL_AMBIGUOUS'),
 ('two_lf','RESULT_FINAL_AMBIGUOUS'),('refusal','PROVIDER_REFUSED'),
 ('failed','EXECUTION_INCOMPLETE'),('cross_invocation','RESULT_FINAL_AMBIGUOUS')])
def test_sequence_and_final_identity_reject_ambiguity(tmp_path,case,code):
    value=events([message('final')]);raw=b'final'
    if case=='conflicting_item':value.insert(3,message('changed'))
    if case=='duplicate_terminal':value.append({'type':'turn.completed'})
    if case=='after_terminal':value.append(message('late','item_1'))
    if case=='no_turn':value.pop(1)
    if case=='no_thread':value.pop(0)
    if case=='commentary_only':value[2]['item']['phase']='commentary'
    if case=='earlier_match':value.insert(3,message('other','item_1'))
    if case=='extra_whitespace':raw=b' final '
    if case=='two_lf':raw=b'final\n\n'
    if case=='refusal':value[2]['item']['type']='refusal'
    if case=='failed':value[-1]={'type':'turn.failed'}
    if case=='cross_invocation':raw=b'other invocation'
    with pytest.raises(store.ExecutionFailure) as caught:extract(tmp_path,value,raw)
    assert caught.value.code==code


def test_duplicate_stable_item_is_idempotent_not_an_extra_answer(tmp_path):
    item=message('final')
    assert extract(tmp_path,events([item,item]))[0]=='final'


def test_stale_file_and_fifo_rejected_without_blocking(tmp_path):
    stream=store.EventStream()
    for event in events([message('final')]):stream.accept(event)
    path=tmp_path/'final';path.write_text('final');os.utime(path,(1,1))
    with pytest.raises(store.ExecutionFailure,match='RESULT_FILE_INVALID'):stream.extract(path,started_ns=time.time_ns())
    path.unlink();os.mkfifo(path)
    with pytest.raises(store.ExecutionFailure,match='RESULT_FILE_INVALID'):stream.extract(path)


def invoke(tmp_path,body,**kwargs):
    root=tmp_path/'private';exe=cli_fixture(tmp_path,body)
    return execution.codex_document(str(exe),'OFFLINE_FIXTURE','synthetic prompt',tmp_path,
        kwargs.pop('cancel',threading.Event()),lambda _:None, diagnostics_root=root,
        invocation={'execution_id':'execution_fixture','project_id':7,'phase':'planner','input_sha256':'b'*64,'plan_hash':'c'*64}, **kwargs)


def body(text='final',tail=''):
    return 'p=Path(sys.argv[sys.argv.index("--output-last-message")+1]);p.write_text('+repr(text)+')\nprint(json.dumps('+repr(message('final'))+'),flush=True)\n'+tail


def read_receipt(root):
    paths=list((root/'private').glob('invocation_*/receipt.json'));assert len(paths)==1
    return paths[0].parent,json.loads(paths[0].read_bytes())


def test_failed_extraction_is_replayable_after_product_cleanup_and_restart(tmp_path):
    with pytest.raises(execution.ExecutionFailure) as caught:
        invoke(tmp_path,body('wrong','print(json.dumps({"type":"turn.completed"}))\n'))
    assert caught.value.code=='RESULT_FINAL_AMBIGUOUS'
    path,receipt=read_receipt(tmp_path)
    # TemporaryDirectory uses the configured platform temp root, not always
    # /private/tmp on macOS. Assert the actual root as well as the cleanup result.
    assert not (Path(tempfile.gettempdir())/receipt['binding']['result_directory_nonce']).exists()
    assert caught.value.evidence['temporary_result_cleanup']=='REMOVED'
    assert (path/'final.bin').read_bytes()==b'wrong'
    assert receipt['final_sha256']==hashlib.sha256(b'wrong').hexdigest()
    assert json.loads((path/'messages.json').read_bytes())[0]['text']=='final'
    assert receipt['state']=='FAILED' and receipt['failure_point']==caught.value.code
    assert store.recover(tmp_path/'private','execution_fixture')['persistence']=='SAVED'
    assert path.stat().st_mode & 0o777==0o700
    assert all(p.stat().st_mode & 0o777==0o600 for p in path.iterdir())
    assert 'wrong' not in json.dumps(caught.value.evidence)


@pytest.mark.parametrize('mode',['timeout','cancel'])
def test_interrupted_process_retains_diagnostics_and_exit_before_cleanup(tmp_path,monkeypatch,mode):
    cancel=threading.Event();original=store.EvidenceReceipt.capture
    def trigger_after_observed_output(self,*args,**kwargs):
        result=original(self,*args,**kwargs)
        if kwargs.get('state')=='RUNNING' and result.get('final_file_state')=='READ':
            if mode=='cancel':cancel.set()
            else:monkeypatch.setattr(execution,'EXECUTION_TIMEOUT_SECONDS',0)
        return result
    # Trigger at the phase under test, not a wall-clock assumption about Python
    # startup. Only the product captures the response; the test never copies it.
    monkeypatch.setattr(store.EvidenceReceipt,'capture',trigger_after_observed_output)
    with pytest.raises(execution.ExecutionFailure) as caught:
        invoke(tmp_path,body('final','import time\ntime.sleep(20)\n'),cancel=cancel)
    assert caught.value.code==('EXECUTION_CANCELLED' if mode=='cancel' else 'EXECUTION_TIMEOUT')
    path,receipt=read_receipt(tmp_path)
    assert receipt['exit_code']==-15
    assert (path/'final.bin').read_bytes()==b'final'
    assert receipt['state']=='FAILED'


def test_capture_failure_does_not_claim_replay_or_restart_cli(tmp_path,monkeypatch):
    original=store.atomic;calls=[]
    def fail(path,raw):
        if path.name=='final.bin':raise OSError('synthetic disk full')
        return original(path,raw)
    monkeypatch.setattr(store,'atomic',fail)
    with pytest.raises(execution.ExecutionFailure) as caught:invoke(tmp_path,body('final','print(json.dumps({"type":"turn.completed"}))\n'))
    assert caught.value.code=='EVIDENCE_WRITE_FAILED'
    assert caught.value.evidence['cli_invocations']==1
    assert caught.value.evidence['private_evidence']['persistence']=='FAILED'
    assert caught.value.evidence['private_evidence']['payload_state']=='NOT_CONFIRMED'
    assert len(list((tmp_path/'private').glob('invocation_*')))==1


@pytest.mark.parametrize('live',[False,True])
def test_group_signal_denial_requires_independent_no_survivors_proof(monkeypatch,live):
    from twos_runtime.codex_adapter import _catalog_group_has_live_members
    child=subprocess.Popen([sys.executable,'-c','import time; print("ready",flush=True); time.sleep(20)' if live else 'print("ready",flush=True)'],
                           stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,text=True)
    original=os.killpg
    try:
        assert child.stdout.readline().strip()=='ready'
        if not live:
            assert child.stdout.read()==''
            deadline=time.monotonic()+3
            while _catalog_group_has_live_members(child):
                assert time.monotonic()<deadline
                time.sleep(.01)
        def denied(pid,stop_signal):
            assert pid==child.pid and stop_signal==signal.SIGTERM
            raise PermissionError(errno.EPERM,'synthetic signal denial')
        monkeypatch.setattr(execution.os,'killpg',denied)
        if live:
            with pytest.raises(PermissionError):execution._signal_document_group(child,signal.SIGTERM)
            assert _catalog_group_has_live_members(child)
        else:
            execution._signal_document_group(child,signal.SIGTERM)
            assert child.wait(timeout=3)==0
    finally:
        if child.poll() is None:
            original(child.pid,signal.SIGKILL)
        child.wait(timeout=3)
        child.stdout.close();child.stderr.close()


def test_evidence_cannot_start_when_private_directory_is_unwritable(tmp_path,monkeypatch):
    def fail(*args):raise OSError('synthetic disk full')
    monkeypatch.setattr(store,'atomic',fail)
    with pytest.raises(execution.ExecutionFailure) as caught:invoke(tmp_path,body())
    assert caught.value.code=='EVIDENCE_WRITE_FAILED'
    assert caught.value.evidence['cli_invocations']==0


def test_secret_payload_is_withheld_but_hash_and_failure_survive(tmp_path):
    # Synthetic secret pattern; not an actual credential.
    secret='sk-'+('Z'*48)
    with pytest.raises(execution.ExecutionFailure):invoke(tmp_path,body(secret,'print(json.dumps({"type":"turn.completed"}))\n'))
    path,receipt=read_receipt(tmp_path)
    assert receipt['payload_state']=='WITHHELD_SECRET'
    assert not (path/'final.bin').exists() and not (path/'messages.json').exists()
    assert receipt['final_sha256']==hashlib.sha256(secret.encode()).hexdigest()


def test_recovery_does_not_resume_and_reports_partial_evidence(tmp_path):
    receipt=store.EvidenceReceipt(tmp_path/'private',{'execution_id':'interrupted'})
    got=store.recover(tmp_path/'private','interrupted')
    assert got['state']=='INTERRUPTED' and got['evidence_complete'] is False
    assert got['payload_state']=='FINAL_UNAVAILABLE'
    assert store.recover(tmp_path/'private','unrecorded')['persistence']=='MISSING'


def test_bounded_retention_never_deletes_active_receipts(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'MAX_RECEIPTS',3)
    root=tmp_path/'private'
    active=store.EvidenceReceipt(root,{'execution_id':'active'})
    old=store.EvidenceReceipt(root,{'execution_id':'old'})
    old.capture(None,None,exit_code=0,failure=None,state='CAPTURED')
    newer=store.EvidenceReceipt(root,{'execution_id':'newer'})
    newer.capture(None,None,exit_code=1,failure='TEST_ONLY',state='FAILED')
    final=store.EvidenceReceipt(root,{'execution_id':'final'})
    assert active.path.exists() and final.path.exists()
    assert len(list(root.glob('invocation_*')))==3
    assert not old.path.exists()
    store.EvidenceReceipt(root,{'execution_id':'third_active'})
    with pytest.raises(OSError):store.EvidenceReceipt(root,{'execution_id':'at_capacity'})


def test_conflicting_explicit_finals_and_late_message_rejected(tmp_path):
    for messages in ([message('first','one','final_answer'),message('final','two','final_answer')],
                     [message('first','one','final_answer'),message('final','two')]):
        with pytest.raises(store.ExecutionFailure,match='RESULT_FINAL_AMBIGUOUS'):
            extract(tmp_path,events(messages))
