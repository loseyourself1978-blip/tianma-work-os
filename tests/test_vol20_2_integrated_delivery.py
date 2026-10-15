"""Integrated workflow behavior; model doubles are explicit, never real evidence."""
import base64
import json
from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient
from sqlalchemy import select
from tests.test_vol20_2_workbench import wb, connected, chat, send, wait, begin, verify, PASSWORD
from twos_runtime.workbench_models import Delivery, ChatMessage
from twos_runtime.workbench_delivery import split_reply, ACTIVE
from twos_runtime.app import create_app
from twos_runtime.execution_evidence import ExecutionFailure

SPEC={'title':'Trip checklist','objective':'Build a mobile checklist with editable items.','deliverables':['Responsive index.html'],'checks':['Add and toggle items'],'model_reason':'Connected coding model'}


def proposal(wb):
    c=connected(wb);app=wb[1];cid=chat(c)
    app.state.discussion.runner=lambda *a,**kw: ('I will build the checklist.\n```twos-delivery\n'+json.dumps(SPEC)+'\n```',{'test_double':True})
    assert send(c,cid,'Please make a mobile checklist page').status_code==202
    detail=wait(c,cid)
    assert 'twos-delivery' not in detail['messages'][-1]['body']
    return c,cid,detail['deliveries'][-1]


def setup(c,d):
    for step in ['project','team','workspace']:
        r=c.post(f"/api/r2/wb/deliveries/{d['id']}/setup",json={'step':step});assert r.status_code==200,r.text;d=r.json()
    return d


def approve(c,d,key='approve-delivery-once'):
    return c.post(f"/api/r2/wb/deliveries/{d['id']}/decide",json={'decision':'approve','approval_hash':d['approval_hash'],'request_id':key})


def settle(c,cid):
    for _ in range(200):
        d=c.get(f'/api/r2/wb/chats/{cid}').json()['deliveries'][-1]
        if d['state'] not in ACTIVE:return d
        time.sleep(.02)
    raise AssertionError('delivery did not settle')


def runner(calls):
    def run(**kw):
        calls.append(kw)
        phase='review' if kw.get('readonly') else 'execution'
        kw['emit']('thread',{'thread_id':'synthetic-'+phase})
        kw['emit']('turn',{'thread_id':'synthetic-'+phase,'turn_id':'synthetic-turn-'+phase})
        text='Reviewed actual fixture files.\n```twos-review\n{"verdict":"pass"}\n```' if kw.get('readonly') else 'Created index.html; synthetic test report.'
        if not kw.get('readonly'):(kw['cwd']/'index.html').write_text('<!doctype html><title>Trip</title><h1>Checklist</h1>')
        kw['emit']('item/completed',{'item':{'id':phase+'-message','type':'agentMessage','text':text,'phase':'final_answer'}})
        return text,{'test_double':True,'thread_id':'synthetic-'+phase,'turn_status':'completed','tool_actions':1}
    return run


def test_single_approval_automatic_review_durable_result_and_idempotency(wb):
    c,cid,d=proposal(wb);calls=[];wb[1].state.deliveries.runner=runner(calls)
    assert d['state']=='PROPOSED' and not calls
    d=setup(c,d);assert d['state']=='READY' and not calls
    assert approve(c,d).status_code==202
    done=settle(c,cid);assert done['state']=='COMPLETED',done
    assert len(calls)==2 and calls[1]['readonly'] is True and calls[1].get('thread_id','')==''
    assert approve(c,d).status_code==202 and len(calls)==2
    body=c.get(f'/api/r2/wb/chats/{cid}').json()
    assert sum(m['role']=='execution' for m in body['messages'])==1
    artifact=c.get(f"/api/r2/wb/deliveries/{d['id']}/files/index.html")
    assert artifact.status_code==200 and 'sandbox allow-scripts' in artifact.headers['content-security-policy']
    assert 'allow-same-origin' not in artifact.headers['content-security-policy']
    assert c.get(f"/api/r2/wb/deliveries/{d['id']}/download").status_code==200
    with TestClient(create_app(wb[3],start_scheduler=False)) as restart:
        restart.cookies.update(dict(c.cookies));got=restart.get(f'/api/r2/wb/chats/{cid}').json()
        assert got['deliveries'][0]['state']=='COMPLETED' and len(calls)==2


def test_setup_order_and_changed_configuration_invalidate_old_approval(wb):
    c,cid,d=proposal(wb)
    assert c.post(f"/api/r2/wb/deliveries/{d['id']}/setup",json={'step':'workspace'}).status_code==409
    d=setup(c,d);old=d['approval_hash']
    r=c.post(f"/api/r2/wb/projects/{d['project_id']}/configuration",json={'planner':'other-model','executor':'other-model','reviewer':'other-model'})
    assert r.status_code==200
    assert approve(c,d).status_code==409
    new=c.get(f'/api/r2/wb/chats/{cid}').json()['deliveries'][-1]
    assert new['approval_hash']!=old and new['configuration']['executor']=='other-model'
    assert wb[1].state.deliveries.jobs=={}


def test_reject_has_no_calls_and_new_proposal_supersedes_only_unstarted(wb):
    c,cid,d=proposal(wb);d=setup(c,d)
    assert c.post(f"/api/r2/wb/deliveries/{d['id']}/decide",json={'decision':'reject','approval_hash':d['approval_hash'],'request_id':'reject-delivery-once'}).status_code==202
    assert send(c,cid,'Change the page design').status_code==202
    detail=wait(c,cid)
    assert [d['state'] for d in detail['deliveries']]==['REJECTED','PROPOSED']
    assert wb[1].state.deliveries.jobs=={}


def test_provider_limit_preserves_files_and_resumes_review_without_execution_replay(wb):
    c,cid,d=proposal(wb);d=setup(c,d);calls=[];base=runner(calls)
    def limited(**kw):
        if kw.get('readonly'):raise ExecutionFailure('PROVIDER_ALLOWANCE_UNAVAILABLE',{'reset_at':'provider-owned'})
        return base(**kw)
    wb[1].state.deliveries.runner=limited
    assert approve(c,d).status_code==202
    done=settle(c,cid);assert done['state']=='NEEDS_ATTENTION' and done['phase']=='review'
    assert done['output'] and (Path(d['configuration']['workspace'])/'index.html').exists()
    wb[1].state.deliveries.runner=base
    assert c.post(f"/api/r2/wb/deliveries/{d['id']}/continue",json={'body':'Continue the saved review','request_id':'continue-review-once'}).status_code==202
    done=settle(c,cid);assert done['state']=='COMPLETED'
    assert len(calls)==2 and sum(not x.get('readonly') for x in calls)==1


def test_pending_approval_scoped_and_delete_blocked(wb):
    c,cid,d=proposal(wb);d=setup(c,d);seen=[];ready=threading.Event()
    def pending(**kw):
        if kw.get('readonly'):return 'Reviewed\n```twos-review\n{"verdict":"pass"}\n```',{'test_double':True,'tool_actions':1}
        kw['emit']('thread',{'thread_id':'synthetic-thread'})
        kw['emit']('turn',{'thread_id':'synthetic-thread','turn_id':'synthetic-turn'})
        kw['emit']('approval',{'request_id':17,'method':'item/commandExecution/requestApproval','params':{'threadId':'synthetic-thread','turnId':'synthetic-turn','command':'python3 test.py','reason':'Run the project test','cwd':str(kw['cwd']),'additionalPermissions':{'fileSystem':{'read':[str(kw['cwd'])]}}}})
        ready.set()
        for _ in range(300):
            entries=kw['controls']()
            if entries:
                (kw['cwd']/'result.txt').write_text('synthetic artifact')
                seen.extend(entries);return 'Finished',{'test_double':True,'tool_actions':1}
            if kw['cancel'].is_set():raise ExecutionFailure('EXECUTION_CANCELLED')
            time.sleep(.01)
        raise AssertionError('approval timeout')
    wb[1].state.deliveries.runner=pending
    assert approve(c,d).status_code==202 and ready.wait(3)
    detail=c.get(f'/api/r2/wb/chats/{cid}').json()['deliveries'][-1]
    assert c.post(f'/api/r2/wb/chats/{cid}/delete',json={'confirmation':True}).status_code==409
    ev=next(e for e in detail['events'] if e['kind']=='approval')
    assert c.post(f"/api/r2/wb/deliveries/{d['id']}/respond",json={'event_id':ev['id']+999,'decision':'approve'}).status_code==404
    assert c.post(f"/api/r2/wb/deliveries/{d['id']}/respond",json={'event_id':ev['id'],'decision':'approve'}).status_code==200
    assert settle(c,cid)['state']=='COMPLETED' and seen[0]['result']=={'decision':'accept'}
    assert c.post(f"/api/r2/wb/deliveries/{d['id']}/respond",json={'event_id':ev['id'],'decision':'approve'}).status_code==409


def test_cross_account_cannot_read_run_download_or_configure(wb):
    c,cid,d=proposal(wb);d=setup(c,d)
    c.post('/api/auth/logout');ch=begin(c,email='other-delivery@example.test');assert verify(c,ch,wb[2]).status_code==200
    assert c.get(f'/api/r2/wb/chats/{cid}').status_code==404
    assert approve(c,d).status_code==404
    assert c.get(f"/api/r2/wb/deliveries/{d['id']}/download").status_code==404
    assert c.post(f"/api/r2/wb/projects/{d['project_id']}/configuration",json={'planner':'x','executor':'x','reviewer':'x'}).status_code==404


def test_source_import_review_and_no_overwrite_or_path_escape(wb):
    c,cid,d=proposal(wb);d=setup(c,d);pid=d['project_id']
    upload=lambda name,text:{'path':name,'data':base64.b64encode(text.encode()).decode()}
    assert c.post(f'/api/r2/wb/projects/{pid}/source/preview',json={'files':[upload('../bad.py','x')]}).status_code==422
    r=c.post(f'/api/r2/wb/projects/{pid}/source/preview',json={'files':[upload('app/main.py','print(1)'),upload('.env','private setting')]}).json()
    assert [f['path'] for f in r['files']]==['app/main.py'] and r['skipped']==['.env']
    payload={'preview_id':r['id'],'sha256':r['sha256'],'confirmation':True}
    assert c.post(f'/api/r2/wb/projects/{pid}/source/confirm',json=payload).status_code==200
    assert c.post(f'/api/r2/wb/projects/{pid}/source/confirm',json=payload).status_code==200
    assert (Path(d['configuration']['workspace'])/'app/main.py').read_text()=='print(1)'
    assert approve(c,d).status_code==409  # source selection changes the reviewed scope


def test_invalid_model_proposal_never_authorizes_or_leaks_structured_text():
    body,spec=split_reply('Readable\n```twos-delivery\n{"title":"x","shell":"rm"}\n```')
    assert body=='Readable' and spec is None
    body,spec=split_reply('Ordinary answer')
    assert body=='Ordinary answer' and spec is None


def test_reply_without_tool_execution_is_not_a_completed_delivery(wb):
    c,cid,d=proposal(wb);d=setup(c,d)
    wb[1].state.deliveries.runner=lambda **kw: ('Here is HTML code, but I did not create a file.',{'tool_actions':0,'test_double':True})
    assert approve(c,d).status_code==202
    done=settle(c,cid)
    assert done['state']=='NEEDS_ATTENTION' and done['phase']=='execution'
    assert done['error_code']=='CODEX_IMPLEMENTATION_NOT_OBSERVED' and done['output']
    assert c.get(f"/api/r2/wb/deliveries/{d['id']}/download").status_code==404


def test_review_findings_and_missing_verification_never_report_complete(wb):
    c,cid,d=proposal(wb);d=setup(c,d);calls=[];base=runner(calls)
    def finding(**kw):
        if kw.get('readonly'):return 'The add button is broken.\n```twos-review\n{"verdict":"changes_required"}\n```',{'tool_actions':1,'test_double':True}
        return base(**kw)
    wb[1].state.deliveries.runner=finding
    assert approve(c,d).status_code==202
    done=settle(c,cid)
    assert done['state']=='NEEDS_ATTENTION' and done['error_code']=='REVIEW_CHANGES_REQUIRED'
    assert 'twos-review' not in done['review'] and 'add button' in done['review']
    assert c.get(f"/api/r2/wb/deliveries/{d['id']}/files/index.html").status_code==200


def test_artifact_snapshot_survives_later_workspace_changes_and_rejects_tampering(wb):
    from twos_runtime.project_first import preference
    c,cid,d=proposal(wb);d=setup(c,d);wb[1].state.deliveries.runner=runner([])
    assert approve(c,d).status_code==202 and settle(c,cid)['state']=='COMPLETED'
    url=f"/api/r2/wb/deliveries/{d['id']}/files/index.html";original=c.get(url).content
    root=Path(d['configuration']['workspace']);(root/'index.html').write_text('later iteration')
    assert c.get(url).content==original
    with wb[1].state.session_factory() as session: snapshot=preference(session,'wb:artifacts:'+d['id'])
    path=Path(snapshot['path'])/'index.html';path.unlink();path.symlink_to(root/'index.html')
    assert c.get(url).status_code==409
    assert c.get(f"/api/r2/wb/deliveries/{d['id']}/download").status_code==409


def test_project_file_export_rejects_links_and_excludes_tool_temporary_state(tmp_path):
    from twos_runtime.workbench_delivery import project_files,read_project_file
    import pytest
    root=tmp_path/'project';root.mkdir();(root/'safe.txt').write_text('safe')
    outside=tmp_path/'not-in-project.txt';outside.write_text('synthetic canary')
    (root/'outside.txt').symlink_to(outside);(root/'other').symlink_to(tmp_path,target_is_directory=True)
    (root/'.twos').mkdir();(root/'.twos'/'cache.txt').write_text('temporary')
    assert [f['path'] for f in project_files(root)]==['safe.txt']
    with pytest.raises(OSError):read_project_file(root,'outside.txt')
    with pytest.raises(OSError):read_project_file(root,'other/not-in-project.txt')


def test_permissions_cannot_escape_project_or_write_during_review(tmp_path):
    from twos_runtime.workbench_delivery import validate_permissions
    from fastapi import HTTPException
    import pytest
    root=tmp_path/'project';root.mkdir();(root/'escape').symlink_to(tmp_path,target_is_directory=True)
    validate_permissions({'fileSystem':{'read':[str(root)]}},root,True)
    validate_permissions({'fileSystem':{'write':[str(root/'src')]}},root)
    for path in (str(tmp_path),str(root/'escape'/'outside'),str(root/'.env'),'relative-path'):
        with pytest.raises(HTTPException):validate_permissions({'fileSystem':{'read':[path]}},root)
    with pytest.raises(HTTPException):validate_permissions({'fileSystem':{'write':[str(root/'index.html')]}},root,True)
    with pytest.raises(HTTPException):validate_permissions({'fileSystem':{'entries':[{'path':{'type':'special','value':{'kind':'root'}},'access':'read'}]}},root)
    with pytest.raises(HTTPException):validate_permissions({'futureGlobalGrant':True},root)


def test_source_copy_configuration_and_planner_model_persist_between_handoffs(wb):
    c,cid,d=proposal(wb);d=setup(c,d);pid=d['project_id']
    r=c.post(f'/api/r2/wb/projects/{pid}/source/preview',json={'files':[{'path':'main.py','data':base64.b64encode(b'print(1)').decode()}]}).json()
    c.post(f'/api/r2/wb/projects/{pid}/source/confirm',json={'preview_id':r['id'],'sha256':r['sha256'],'confirmation':True}).raise_for_status()
    c.post(f'/api/r2/wb/projects/{pid}/configuration',json={'planner':'chosen-planner','executor':'chosen-executor','reviewer':'chosen-reviewer'}).raise_for_status()
    seen=[]
    def discuss(executable,model,prompt,*a,**kw):
        seen.append(model);return 'Updated\n```twos-delivery\n'+json.dumps(SPEC)+'\n```',{'test_double':True}
    wb[1].state.discussion.runner=discuss
    assert send(c,cid,'Use the imported source for this iteration').status_code==202
    new=setup(c,wait(c,cid)['deliveries'][-1])
    assert seen==['chosen-planner'] and new['configuration']['source_hash']==r['sha256']
    detail=c.get(f'/api/r2/projects/{pid}').json()
    assert detail['integrated']['workspace']['kind']=='source-copy' and len(detail['deliveries'])==2


def test_requested_configuration_updates_existing_team_without_execution(wb,monkeypatch):
    from twos_runtime import tool_recovery
    monkeypatch.setattr(tool_recovery,'local_model_catalog',lambda:['synthetic-model','new-reviewer'])
    c,cid,pending=proposal(wb);pending=setup(c,pending);pid=pending['project_id']
    spec={**SPEC,'kind':'configuration','team':{'reviewer':'new-reviewer'}}
    wb[1].state.discussion.runner=lambda *a,**kw:('Updating the review model.\n```twos-delivery\n'+json.dumps(spec)+'\n```',{'test_double':True})
    assert send(c,cid,'Change only the review model').status_code==202
    detail=wait(c,cid);assert detail['deliveries'][0]['state']=='READY'
    configured=setup(c,detail['deliveries'][-1])
    assert configured['state']=='CONFIGURED' and configured['project_id']==pid
    assert c.get(f'/api/r2/projects/{pid}').json()['integrated']['team']['reviewer']=='new-reviewer'
    assert approve(c,pending).status_code==409
    assert approve(c,configured).status_code==409 and not wb[1].state.deliveries.jobs


def test_source_file_directory_conflict_is_rejected_without_partial_copy(wb):
    c,cid,d=proposal(wb);d=setup(c,d)
    payload={'files':[{'path':n,'data':base64.b64encode(b'example').decode()} for n in ['main.py','main.py/child.py']]}
    assert c.post(f"/api/r2/wb/projects/{d['project_id']}/source/preview",json=payload).status_code==422
    assert not list(Path(d['configuration']['workspace']).iterdir())


def test_connection_binds_selected_client_catalog_before_any_discussion(wb,monkeypatch):
    from types import SimpleNamespace
    from tests.test_vol20_2_workbench import account
    from twos_runtime import workbench,workbench_codex
    c=account(wb);seen=[]
    monkeypatch.setattr(workbench.subprocess,'run',lambda *a,**kw:SimpleNamespace(returncode=0,stdout=b'Logged in using ChatGPT',stderr=b''))
    def catalog(executable,root):seen.append(executable);return ['synthetic-model']
    monkeypatch.setattr(workbench_codex,'advertised_models',catalog)
    body={'tool_id':'test-tool','model':'absent-model','confirmation':True,'existing_plan_only':True}
    assert c.post('/api/r2/wb/connect',json=body).status_code==409
    assert c.get('/api/r2/wb/state').json()['connection'] is None
    result=c.post('/api/r2/wb/connect',json={**body,'model':'synthetic-model'})
    assert result.status_code==200 and result.json()['available_models']==['synthetic-model']
    assert c.get('/api/r2/tools').json()['models']==['synthetic-model']
    assert seen==['/synthetic/codex','/synthetic/codex'] and not wb[1].state.discussion.jobs


def test_old_delivery_cannot_resume_over_a_running_project(wb):
    c,cid,old=proposal(wb);old=setup(c,old)
    with wb[1].state.session_factory() as s:
        row=s.get(Delivery,old['id']);row.state='INTERRUPTED';s.commit()
    assert send(c,cid,'Another approved scope').status_code==202
    new=setup(c,wait(c,cid)['deliveries'][-1])
    with wb[1].state.session_factory() as s:
        row=s.get(Delivery,new['id']);row.state='RUNNING';s.commit()
    r=c.post(f"/api/r2/wb/deliveries/{old['id']}/continue",json={'request_id':'conflicting-recovery','body':'Continue'})
    assert r.status_code==409 and r.json()['error']['code']=='PROJECT_EXECUTION_BUSY'
    assert not wb[1].state.deliveries.jobs


def test_changed_executable_is_rejected_before_runner(wb,monkeypatch):
    from twos_runtime import tool_recovery
    c,cid,d=proposal(wb);d=setup(c,d);calls=[];wb[1].state.deliveries.runner=runner(calls)
    monkeypatch.setattr(tool_recovery,'candidates',lambda _:[])
    assert approve(c,d).status_code==202
    result=settle(c,cid)
    assert result['error_code']=='EXECUTABLE_MISSING_OR_CHANGED' and not calls


def test_source_credential_filter_keeps_code_references_but_excludes_values(wb):
    from twos_runtime.workbench_delivery import source_contains_secrets
    assert not source_contains_secrets('app.py','password = payload.password\npassword = private_bytes(value)')
    assert not source_contains_secrets('app.js','const form = {password: fields.password.value};')
    assert source_contains_secrets('settings.py','password = "SyntheticCredentialValue123"')
    assert source_contains_secrets('settings.json','{"password":"SyntheticCredentialValue123"}')
    assert source_contains_secrets('settings.ini','password = SyntheticCredentialValue123')
    c,cid,d=proposal(wb);d=setup(c,d)
    files={'app.py':'password = payload.password','auth.json':'{}','Credentials.json':'{}','settings.py':'password = "SyntheticCredentialValue123"'}
    r=c.post(f"/api/r2/wb/projects/{d['project_id']}/source/preview",json={'files':[{'path':k,'data':base64.b64encode(v.encode()).decode()} for k,v in files.items()]})
    assert r.status_code==200 and [f['path'] for f in r.json()['files']]==['app.py']
    assert set(r.json()['skipped'])=={'auth.json','Credentials.json','settings.py'}
