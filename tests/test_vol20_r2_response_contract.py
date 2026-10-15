"""Offline contract and mutation controls. These never contact a real provider."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from twos_runtime import iteration_contract as contract, iteration_studio as studio
from twos_runtime.project_execution import codex_document, ExecutionFailure, extract_final_result
from tests.test_vol20_r2_structured_iteration import source, patch, invariant


def test_original_failure_bytes_rejected_without_repair(source):
    root,baseline=source
    output=(Path(__file__).parent/'fixtures/r2_contract/execution_9_rejected.txt').read_text()
    value=json.loads(output)
    assert 'summary' not in value and set(value['replacement'])=={'noSourcesDesc'}
    before=(root/studio.CATALOG).read_bytes();index=invariant(root)
    with pytest.raises(HTTPException) as e:studio.apply_structured_patch(root,baseline,output)
    assert e.value.detail['code']=='ITERATION_PATCH_FORMAT_INVALID'
    assert (root/studio.CATALOG).read_bytes()==before and invariant(root)==index
    assert not (root/studio.REGRESSION).exists()


@pytest.mark.parametrize('mutation',['missing_summary','nested','extra','wrong_type','duplicate','truncated','fenced'])
def test_single_schema_rejects_ambiguous_shapes(source,mutation):
    root,baseline=source;v=patch(root,baseline)
    if mutation=='missing_summary':v.pop('summary')
    if mutation=='nested':v['replacement']={'noSourcesDesc':v['replacement']}
    if mutation=='extra':v['path']='outside'
    if mutation=='wrong_type':v['summary']=False
    out=json.dumps(v)
    if mutation=='duplicate':out=out[:-1]+',"summary":"other"}'
    if mutation=='truncated':out=out[:-3]
    if mutation=='fenced':out='```json\n'+out+'\n```'
    with pytest.raises(ValueError):contract.parse(out,'executor')


@pytest.mark.parametrize('mutation,code',[
    ('unchanged','ITERATION_NO_CHANGES'),('en_only','ITERATION_BOTH_LOCALES_REQUIRED'),
    ('zh_only','ITERATION_BOTH_LOCALES_REQUIRED'),('non_target','ITERATION_SCOPE_VIOLATION')])
def test_independent_platform_detects_catalog_faults(source,mutation,code):
    root,baseline=source
    before=json.loads(studio.git(root,'show',baseline+':'+studio.CATALOG));after=copy.deepcopy(before)
    after['noSourcesDesc']=patch(root,baseline)['replacement']
    assert studio.verify_catalog_delta(before,after)['both_locales_changed']
    if mutation=='unchanged':after['noSourcesDesc']=copy.deepcopy(before['noSourcesDesc'])
    if mutation=='en_only':after['noSourcesDesc']['zh-CN']=before['noSourcesDesc']['zh-CN']
    if mutation=='zh_only':after['noSourcesDesc']['en-US']=before['noSourcesDesc']['en-US']
    if mutation=='non_target':after['guard']['en-US']='corrupted'
    with pytest.raises(HTTPException) as e:studio.verify_catalog_delta(before,after)
    assert e.value.detail['code']==code


def test_generated_regression_sensitivity_and_tautology(source,monkeypatch):
    from twos_runtime import iteration_candidate as candidate
    root,baseline=source;value=patch(root,baseline)
    studio.apply_structured_patch(root,baseline,json.dumps(value))
    # This offline unit test uses a synthetic unittest in a subprocess. Packaged
    # GUI validation separately executes the same controls under sandbox-exec.
    def run(path,app,*,expect_pass=True):
        code='import sys;from twos_runtime.iteration_candidate import check_main;sys.exit(check_main(sys.argv[1:]))'
        result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True)
        r=json.loads(result.stdout)
        if expect_pass and not r['passed']:studio.fail('ITERATION_TEST_FAILED')
        if not expect_pass and (r['passed'] or r['errors'] or not r['failures']):studio.fail('ITERATION_REGRESSION_INSENSITIVE')
        return r
    monkeypatch.setattr(candidate,'run_regression',run)
    result=candidate.validate_generated_regression(root,baseline,Path('/synthetic-only'))
    assert len(result['negative_controls'])==3
    assert all(not r['passed'] and r['failures'] for r in result['negative_controls'].values())
    test=(root/studio.REGRESSION).read_text()
    test=test.replace('self.assertEqual(data["noSourcesDesc"], {"en-US":"Synthetic fixture changed","zh-CN":"合成替身已改变"})','self.assertEqual(data["noSourcesDesc"],data["noSourcesDesc"])')
    (root/studio.REGRESSION).write_text(test)
    with pytest.raises(HTTPException) as e:candidate.validate_generated_regression(root,baseline,Path('/synthetic-only'))
    assert e.value.detail['code']=='ITERATION_REGRESSION_INSENSITIVE'


def cli_fixture(tmp_path,body):
    exe=tmp_path/'offline-cli'
    prelude = "import sys,json\nfrom pathlib import Path\n" + "print(json.dumps({'type':'thread.started','thread_id':'fixture-thread'}))\nprint(json.dumps({'type':'turn.started'}))\n"
    exe.write_text('#!'+sys.executable+'\n'+prelude+body)
    exe.chmod(0o700);return exe


@pytest.mark.parametrize('case,code',[
    ('missing','RESULT_FILE_UNAVAILABLE'),('symlink','RESULT_FILE_UNAVAILABLE'),
    ('hardlink','RESULT_FILE_INVALID'),('empty','RESULT_FILE_INVALID'),('mismatch','RESULT_FINAL_AMBIGUOUS'),
    ('multiple','RESULT_FINAL_AMBIGUOUS'),('nonzero','EXECUTION_INCOMPLETE'),
    ('no_terminal','EXECUTION_INCOMPLETE'),('event_error','PROVIDER_REQUEST_FAILED'),
    ('partial_event','RESULT_EVENT_STREAM_INCOMPLETE'),('non_utf8','RESULT_FILE_UNAVAILABLE')])
def test_final_file_and_events_fail_closed(tmp_path,case,code):
    body='p=Path(sys.argv[sys.argv.index("--output-last-message")+1]);assert not p.exists()\n'
    if case=='symlink':body+='old=p.parent/"old";old.write_text("fixture");p.symlink_to(old)\n'
    elif case=='hardlink':body+='import os\nold=p.parent/"old";old.write_text("fixture");os.link(old,p)\n'
    elif case=='non_utf8':body+='p.write_bytes(b"\\xff")\n'
    elif case!='missing':body+='p.write_text('+repr('' if case=='empty' else 'wrong' if case=='mismatch' else 'fixture')+')\n'
    body+='print(json.dumps({"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"fixture"}}))\n'
    if case=='multiple':body+='print(json.dumps({"type":"item.completed","item":{"id":"item_1","type":"agent_message","text":"second"}}))\n'
    if case!='no_terminal':body+='print(json.dumps({"type":"turn.completed"}))\n'
    if case=='event_error':body+='print(json.dumps({"type":"error","message":"synthetic refusal"}))\n'
    if case=='partial_event':body+='print("{",end="")\n'
    if case=='nonzero':body+='sys.exit(3)\n'
    exe=cli_fixture(tmp_path,body)
    with pytest.raises(ExecutionFailure) as e:codex_document(str(exe),'offline','fixture',tmp_path,threading.Event(),lambda _:None)
    assert e.value.code==code
    assert e.value.evidence['cli_invocations']==1


def test_schema_bytes_passed_to_cli_and_final_separate_from_commentary(tmp_path,source):
    root,baseline=source;value=json.dumps(patch(root,baseline));expected=contract.identity()['schemas']['executor']
    body='''import hashlib
sys.stdin.read()
schema=Path(sys.argv[sys.argv.index('--output-schema')+1])
assert hashlib.sha256(schema.read_bytes()).hexdigest()==EXPECTED
assert '--json' in sys.argv and '--ephemeral' in sys.argv
p=Path(sys.argv[sys.argv.index('--output-last-message')+1]);assert not p.exists()
p.write_text(RESULT)
print(json.dumps({'type':'item.completed','item':{'id':'item_0','type':'agent_message','phase':'commentary','text':'process only'}}))
print(json.dumps({'type':'item.completed','item':{'id':'item_1','type':'agent_message','text':RESULT}}))
print(json.dumps({'type':'turn.completed'}))
'''.replace('EXPECTED',repr(expected)).replace('RESULT',repr(value))
    exe=cli_fixture(tmp_path,body)
    result,receipt=codex_document(str(exe),'offline','fixture',root,threading.Event(),lambda _:None,output_schema=contract.schema_path('executor'))
    assert result==value and receipt['response_schema_sha256']==expected
    assert receipt['final_result_extraction']=='PASSED'
    assert contract.parse(result,'executor')==json.loads(value)


def test_shared_engineering_ledger_enforces_total_and_no_duplicate(tmp_path):
    from twos_runtime.engineering_budget import InvocationGate
    root=tmp_path/'environment';root.mkdir();ledger=tmp_path/'ledger.json'
    ledger.write_text(json.dumps({'experiment_id':'fixture','historical_cli_starts':9,'total_limit':15,
        'allowed_environment_data_root':str(root),'remaining_phase_order':['document']*3+['planner','executor','reviewer'],'entries':[]}));ledger.chmod(0o600)
    policy={'environment_data_root':str(root),'experiment_id':'fixture','ledger_path':str(ledger)}
    (root/'engineering-invocation-policy.json').write_text(json.dumps(policy));settings=SimpleNamespace(data_root=root)
    for i,phase in enumerate(['document']*3+['planner','executor','reviewer']):
        g=InvocationGate(settings,'e'+str(i),phase,{'fixture':True});g.started();g.finished(i!=1)
        if i==0:
            with pytest.raises(ValueError):InvocationGate(settings,'e0',phase,{})
    with pytest.raises(ValueError):InvocationGate(settings,'e6','reviewer',{})
    record=json.loads(ledger.read_text())
    assert [x['global_ordinal'] for x in record['entries']]==list(range(10,16))
    assert len(record['entries'])==6 and record['historical_cli_starts']==9
    other=tmp_path/'another';other.mkdir()
    (other/'engineering-invocation-policy.json').write_text(json.dumps({**policy,'environment_data_root':str(other)}))
    with pytest.raises(ValueError):InvocationGate(SimpleNamespace(data_root=other),'wrong','document',{})


def test_lost_start_callback_reservation_cannot_be_reused(tmp_path):
    from twos_runtime.engineering_budget import InvocationGate
    ledger=tmp_path/'ledger.json';root=tmp_path/'env';root.mkdir()
    ledger.write_text(json.dumps({'experiment_id':'fixture','historical_cli_starts':9,'total_limit':10,'allowed_environment_data_root':str(root),'remaining_phase_order':['document'],'entries':[]}));ledger.chmod(0o600)
    (root/'engineering-invocation-policy.json').write_text(json.dumps({'experiment_id':'fixture','environment_data_root':str(root),'ledger_path':str(ledger)}))
    g=InvocationGate(SimpleNamespace(data_root=root),'lost','document',{})
    # Conservative reservation is separate from an observed CLI start.
    assert not json.loads(ledger.read_text())['entries'][0]['cli_started']
    with pytest.raises(ValueError):InvocationGate(SimpleNamespace(data_root=root),'again','document',{})


def test_explicit_audit_only_policy_preserves_history_without_release_cap(tmp_path):
    from twos_runtime.engineering_budget import InvocationGate
    root=tmp_path/'env';root.mkdir();ledger=tmp_path/'audit.json'
    value={'experiment_id':'owner-override-fixture','mode':'AUDIT_ONLY_EXISTING_QUOTA',
           'historical_cli_starts':13,'total_limit':15,'remaining_phase_order':['executor','reviewer'],
           'allowed_environment_data_root':str(root),'entries':[]}
    ledger.write_text(json.dumps(value));ledger.chmod(0o600)
    policy={'environment_data_root':str(root),'experiment_id':value['experiment_id'],'ledger_path':str(ledger),'mode':value['mode']}
    path=root/'engineering-invocation-policy.json';path.write_text(json.dumps(policy))
    settings=SimpleNamespace(data_root=root)
    for i,phase in enumerate(('document','document','document','planner','executor','reviewer')):
        g=InvocationGate(settings,'audit-'+str(i),phase,{'synthetic':True});g.started();g.finished(i!=1)
    saved=json.loads(ledger.read_text())
    assert saved['historical_cli_starts']==13 and saved['total_limit']==15
    assert [e['global_ordinal'] for e in saved['entries']]==list(range(14,20))
    assert sum(e['cli_started'] for e in saved['entries'])==6
    with pytest.raises(ValueError):InvocationGate(settings,'audit-0','document',{})
    path.write_text(json.dumps({**policy,'mode':'CAPPED'}))
    with pytest.raises(ValueError):InvocationGate(settings,'mismatch','document',{})
    assert len(json.loads(ledger.read_text())['entries'])==6


def test_controller_change_invalidates_contract_binding(monkeypatch):
    a=contract.identity();original=Path.read_bytes
    def changed(path):
        value=original(path)
        return value+b'\n# synthetic changed adapter' if path.name=='project_execution.py' else value
    monkeypatch.setattr(Path,'read_bytes',changed)
    b=contract.identity()
    assert a['controller_input_hashes']!=b['controller_input_hashes']
    assert a['schemas']==b['schemas']


def test_final_extraction_rejects_refusal_and_corrupt_event(tmp_path):
    for name,line,expected in [('refusal',json.dumps({'type':'item.completed','item':{'type':'refusal'}}),'PROVIDER_REFUSED'),('corrupt','not-json','RESULT_EVENT_STREAM_INCOMPLETE')]:
        location=tmp_path/name;location.mkdir()
        exe=cli_fixture(location,'p=Path(sys.argv[sys.argv.index("--output-last-message")+1]);p.write_text("fixture")\nprint('+repr(line)+')\nprint(json.dumps({"type":"turn.completed"}))\n')
        with pytest.raises(ExecutionFailure) as e:codex_document(str(exe),'offline','fixture',location,threading.Event(),lambda _:None)
        assert e.value.code==expected
