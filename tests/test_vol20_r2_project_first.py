"""R2 scoped product regression. Model invocations in this file are substitutes."""
import base64
from dataclasses import replace
import hashlib
import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from twos_runtime.app import create_app
from twos_runtime import project_sources,tool_recovery
from twos_runtime.project_first_models import WorkItem,WorkExecution,ProjectSource
from tests.test_vol19_fresh_install_first_run import fresh_settings,start_owner_step,owner_payload,USERNAME,PASSWORD

@pytest.fixture
def product(tmp_path,monkeypatch):
    settings=replace(fresh_settings(tmp_path/'app'),managed_workspace_root=tmp_path/'projects')
    monkeypatch.setattr(tool_recovery,'candidates',lambda _: [{'id':'test-identity','path':'/synthetic/codex','label':'Synthetic adapter — no provider'}])
    app=create_app(settings,start_scheduler=False)
    with TestClient(app) as c:
        start_owner_step(c)
        assert c.post('/api/setup/owner',json=owner_payload(settings)).status_code==201
        yield c,app,settings


def project(c,name='Synthetic LDD',kind='ldd'):
    r=c.post('/api/r2/projects',json={'name':name,'goal':'Synthetic safe goal','kind':kind,'confirmation':True,'request_id':'project-'+name})
    assert r.status_code==201,r.text
    return r.json()['project_id']


def team(c,pid,model='synthetic-model'):
    body={'tool_id':'test-identity','planner':model,'executor':model,'reviewer':model,'request_limit':5,'existing_plan_only':True,'human_gates':['Human technical review']}
    r=c.post(f'/api/r2/projects/{pid}/team',json=body);assert r.status_code==200,r.text
    return body


def task(c,pid,source_ids=None):
    r=c.post(f'/api/r2/projects/{pid}/work',json={'title':'Synthetic source review','body':'List evidence gaps, with citations. No trading.','output_locale':'en-US','source_ids':source_ids or []})
    assert r.status_code==201,r.text
    return r.json()


def approve(c,w):
    r=c.post(f"/api/r2/work/{w['id']}/plan",json={}); assert r.status_code==200,r.text
    w=r.json();r=c.post(f"/api/r2/work/{w['id']}/approve",json={'plan_hash':w['plan_hash'],'ui_locale':'en-US','confirmation':True,'single_model_disclosed':True})
    assert r.status_code==200,r.text
    return r.json()


def test_fresh_three_projects_no_manual_git_gate(product):
    c,app,settings=product
    ids=[project(c,'Synthetic '+k,k) for k in ('ldd','dashu','development')]
    assert len(set(ids))==3
    assert c.get('/api/setup/status').json()['state']=='ready'
    assert len(c.get('/api/r2/projects').json())==3
    assert c.get('/api/r2/preferences').json()['locale']=='en-US'
    for pid in ids:
        d=c.get(f'/api/r2/projects/{pid}').json()
        assert d['sources']==[] and d['works']==[] and d['executions']==[]
        assert d['boundaries']['order_authority']=='NONE'
    assert list(settings.data_root.glob('local-push-tests/*'))==[]


def test_import_selective_credential_exclusion_and_idempotency(product):
    c,app,_=product;pid=project(c)
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        z.writestr('context.md','# Synthetic context\nCurrent track MODEL_A_ONLY.\n')
        z.writestr('.env','secret content must not persist')
        z.writestr('notes.md','api_key = '+ 'z'*40)
    response=c.post(f'/api/r2/projects/{pid}/imports/preview',json={'filename':'safe.zip','data_base64':base64.b64encode(buf.getvalue()).decode()})
    assert response.status_code==200,response.text
    preview=response.json()
    assert [e['classification'] for e in preview['entries']]==['SAFE_IMPORT','DO_NOT_IMPORT','DO_NOT_IMPORT']
    body={'sha256':preview['sha256'],'names':['context.md'],'confirmation':True}
    route=f"/api/r2/projects/{pid}/imports/{preview['preview_id']}/confirm"
    receipt=c.post(route,json=body).json();assert receipt==c.post(route,json=body).json()
    assert c.post(route,json={**body,'names':['.env']}).status_code==409
    d=c.get(f'/api/r2/projects/{pid}').json();assert len(d['sources'])==1
    sid=d['sources'][0]['id']; assert 'MODEL_A_ONLY' in c.get(f'/api/r2/projects/{pid}/sources/{sid}').json()['content']
    second=project(c,'Synthetic other','blank')
    assert c.get(f'/api/r2/projects/{second}/sources/{sid}').status_code==404
    with app.state.session_factory() as s:
        from twos_runtime.project_first_models import ImportPreview
        raw=s.get(ImportPreview,preview['preview_id']).payload_json
        assert 'z'*40 not in raw and 'secret content' not in raw


def test_locale_does_not_mutate_plan_approval_or_invoke(product):
    c,app,_=product;pid=project(c);team(c,pid);w=approve(c,task(c,pid))
    before=c.get(f'/api/r2/projects/{pid}').json()
    assert c.post('/api/r2/preferences',json={'locale':'zh-CN'}).status_code==200
    assert c.get(f'/api/r2/projects/{pid}').json()==before
    assert c.post('/api/r2/preferences',json={'locale':'es'}).status_code==422
    assert c.post('/api/r2/preferences',json={'locale':'en-US'},headers={'Origin':'http://foreign.invalid'}).status_code==403
    assert app.state.project_execution.jobs=={}


def test_document_actual_adapter_boundary_and_duplicate_start(product):
    c,app,_=product;pid=project(c);team(c,pid);w=approve(c,task(c,pid));calls=[]
    def fake(executable,model,prompt,cwd,cancel,on_process,**kw):
        calls.append(prompt)
        return '# Synthetic output\nEvidence gaps remain.',{'test_double':True,'provider_invocations':0,'requested_model':model}
    app.state.project_execution.runner=fake
    body={'plan_hash':w['plan_hash'],'request_id':'single-request-id','confirmation':True}
    route=f"/api/r2/work/{w['id']}/start"
    r=c.post(route,json=body);assert r.status_code==202,r.text
    eid=r.json()['id']; assert c.post(route,json=body).json()['id']==eid
    for _ in range(100):
        d=c.get(f'/api/r2/projects/{pid}').json()
        if d['executions'][0]['state']=='COMPLETED':break
        time.sleep(.02)
    assert len(calls)==1
    assert d['works'][0]['state']=='COMPLETED'
    assert d['executions'][0]['evidence']['test_double'] is True
    assert d['executions'][0]['evidence']['human_gates']['Human technical review']=='PENDING_HUMAN_REVIEW'
    assert d['request_budget']['used']==1
    assert c.post(route,json={**body,'request_id':'another-request-id'}).status_code==409
    assert 'Synthetic output' in c.get(f"/api/r2/work/{w['id']}/export").text


def test_new_tool_invalidates_unstarted_approval_not_history(product):
    c,app,_=product;pid=project(c);config=team(c,pid);w=approve(c,task(c,pid))
    c.post(f'/api/r2/projects/{pid}/team',json={**config,'executor':'other-model'})
    r=c.post(f"/api/r2/work/{w['id']}/start",json={'plan_hash':w['plan_hash'],'request_id':'blocked-request-id','confirmation':True})
    assert r.status_code==409
    d=c.get(f'/api/r2/projects/{pid}').json()
    assert d['works'][0]['state']=='REPLAN_REQUIRED' and d['request_budget']['used']==0
    assert any(e['event']=='PLAN_APPROVED' for e in d['activity'])


def test_saved_projects_survive_restart(product):
    c,app,settings=product;pid=project(c);team(c,pid);w=approve(c,task(c,pid))
    before=c.get(f'/api/r2/projects/{pid}').json()
    with TestClient(create_app(settings,start_scheduler=False)) as next_client:
        assert next_client.post('/api/auth/login',json={'username':USERNAME,'password':PASSWORD}).status_code==200
        assert next_client.get(f'/api/r2/projects/{pid}').json()==before


@pytest.mark.parametrize('name',['../escape.md','/absolute.md','folder/../a.md','a\\b.md','a:stream','a/./b.md'])
def test_import_traversal_rejected(name):
    with pytest.raises(project_sources.SourceError):project_sources.preview(name,b'x')


def test_manifest_validates_actual_source():
    data=b'current source\n';digest=hashlib.sha256(data).hexdigest();buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        z.writestr('wrapper/a.md',data);z.writestr('wrapper/MANIFEST.sha256',digest+'  a.md\n')
    assert project_sources.preview('bundle.zip',buf.getvalue())['manifest_entries_verified']==1


def test_duplicate_unicode_paths_and_symlink_rejected():
    for names in [('A.md','a.md'),('é.md','e\u0301.md')]:
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            for n in names:z.writestr(n,'text')
        with pytest.raises(project_sources.SourceError,match='IMPORT_DUPLICATE_PATH'):project_sources.preview('test.zip',buf.getvalue())
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:
        i=zipfile.ZipInfo('link.md');i.external_attr=0o120777<<16;z.writestr(i,'/private/path')
    with pytest.raises(project_sources.SourceError,match='IMPORT_LINK_OR_ENCRYPTION'):project_sources.preview('test.zip',buf.getvalue())


def test_json_transfer_manifest_checks_exact_payloads():
    def package(changed=False):
        b=io.BytesIO();content=b'Public synthetic context'
        record={'path':'context.md','export_bytes':len(content),'export_sha256':hashlib.sha256(content).hexdigest()}
        with zipfile.ZipFile(b,'w') as z:
            z.writestr('context.md',content+(b'x' if changed else b''))
            z.writestr('ZIP_MANIFEST.json',json.dumps({'files':[record]}))
        return b.getvalue()
    assert project_sources.preview('transfer.zip',package())['manifest_entries_verified']==1
    with pytest.raises(project_sources.SourceError):project_sources.preview('transfer.zip',package(True))


@pytest.mark.parametrize("revise,no_change,deterministic_fail",[(False,False,False),(True,False,False),(False,True,False),(True,True,False),(False,False,True)])
def test_iteration_exact_approval_idempotency_and_separate_review(product,tmp_path,monkeypatch,revise,no_change,deterministic_fail):
    import subprocess
    from twos_runtime.iteration_studio import CATALOG,REGRESSION
    c,app,settings=product;pid=project(c,'Synthetic Development','development');team(c,pid)
    root=tmp_path/'clean-source';root.mkdir()
    for file,content in ((CATALOG,json.dumps({'noSourcesDesc':{'en-US':'No sources yet. Import one.','zh-CN':'尚无资料，请导入。'},'protected':{'en-US':'Guard','zh-CN':'保护'}})),('twos_runtime/app.py','# synthetic bounded fixture'),('scripts/build_macos.py','# not executed'),('tests/.keep','fixture')):
        p=root/file;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
    def git(*args):return subprocess.check_output(['git','-C',str(root),'-c','user.name=Synthetic Test','-c','user.email=synthetic@example.invalid',*args],text=True)
    git('init','-b','main');git('add','.');git('commit','-m','Synthetic baseline')
    before=git('rev-parse','HEAD')
    preview=c.post(f'/api/r2/projects/{pid}/target/preview',json={'path':str(root)})
    assert preview.status_code==200,preview.text
    binding={'preview_hash':preview.json()['preview_hash'],'confirmation':True}
    route=f'/api/r2/projects/{pid}/target/confirm'
    assert c.post(route,json=binding).status_code==200
    assert c.post(route,json=binding).status_code==200
    from twos_runtime import iteration_candidate
    monkeypatch.setattr(iteration_candidate,'bundle_path',lambda:tmp_path/'synthetic-app')
    def regression(root,app):
        if deterministic_fail:
            from twos_runtime.project_first import fail
            fail('ITERATION_TEST_FAILED')
        return {'passed':True,'tests_run':1,'test_substitute':True}
    monkeypatch.setattr(iteration_candidate,'run_regression',regression)
    monkeypatch.setattr(iteration_candidate,'validate_generated_regression',lambda *a:{'status':'PASSED','test_substitute':True})
    calls=[]
    def runner(executable,model,prompt,cwd,cancel,on_process,*,write=False,output_schema=None):
        calls.append(write)
        assert write is False
        assert 'The protected controller, not the generated test, compares ALL non-target entries' in prompt
        assert 'generated unittest must assert the exact new bilingual pair' in prompt
        if 'EXECUTION_PATCH_RESPONSE' in prompt:
            from twos_runtime.iteration_contract import schema_path
            assert output_schema==schema_path('executor')
            assert 'give an actionable import-sources next step' not in prompt
            assert 'APPROVED PLAN' in prompt and 'exact bilingual wording' in prompt
            assert 'CURRENT CATALOG ENTRY' in prompt and 'No sources yet. Import one.' in prompt
            assert 'separately approved implementation phase' in prompt and 'Do not call tools or write files' in prompt
            value=json.loads((cwd/CATALOG).read_text())['noSourcesDesc'] if no_change else {'en-US':'Fixture updated source guidance.','zh-CN':'替身的新资料提示。'}
            return json.dumps({'schema':'twos.iteration.patch.v1','baseline':before.strip(),
                'catalog_sha256':hashlib.sha256((cwd/CATALOG).read_bytes()).hexdigest(),
                'replacement':value,'regression':'# noSourcesDesc en-US zh-CN; test runner is an explicit substitute\n',
                'summary':'Synthetic response only: retain this diagnostic.'}),{'provider_invocations':0,'test_substitute':True,'thread_id':'synthetic-no-change'}
        if 'Review this actual diff' in prompt:
            assert 'Executed regression binding' in prompt and 'tests_run' in prompt and 'Approved plan' in prompt
        return ('{"verdict":"PASS","reason":"Synthetic reviewer, not a provider."}' if 'Review this actual diff' in prompt else 'Synthetic plan or result'),{'provider_invocations':0,'test_substitute':True}
    app.state.project_execution.runner=runner
    def wait():
        for _ in range(100):
            d=c.get(f'/api/r2/projects/{pid}').json()
            if d['works'] and d['works'][-1]['state']!='RUNNING':return d
            time.sleep(.02)
        raise AssertionError('isolated worker timeout')
    req={'body':'Improve empty-source guidance only.','output_locale':'en-US','request_id':'synthetic-iteration-1','confirmation':True}
    first=c.post(f'/api/r2/projects/{pid}/iterations',json=req);assert first.status_code==202,first.text
    d=wait();w=d['works'][-1];assert w['state']=='PLANNED'
    assert c.post(f'/api/r2/projects/{pid}/iterations',json=req).json()['id']==first.json()['id']
    assert len(calls)==1
    if revise:
        from pathlib import Path
        old_snapshot=d['target']['snapshot'];old_hash=w['plan_hash']
        instruction='Add clearer bilingual source guidance and cite the import button.'
        revision={**req,'body':json.dumps({'chat_id':'synthetic-chat','instruction':instruction,'history':[]}), 'request_id':'synthetic-revision-2','expected_revision':1}
        route=f"/api/r2/iterations/{w['id']}/revision/plan"
        revision_result=c.post(route,json=revision);assert revision_result.status_code==202,revision_result.text
        d=wait();w=d['works'][-1]
        assert w['revision']==2 and w['plan_hash']!=old_hash and w['approval']=={}
        assert w['title']==instruction and w['body']==revision['body']
        assert d['target']['snapshot']!=old_snapshot and Path(old_snapshot).is_dir()
        assert c.post(route,json=revision).json()['id']==revision_result.json()['id']
        assert len(calls)==2
    execute=f"/api/r2/iterations/{w['id']}/execute"
    action={'plan_hash':w['plan_hash'],'request_id':'synthetic-execute-1','confirmation':True}
    assert c.post(execute,json=action).status_code==409
    approved=c.post(f"/api/r2/work/{w['id']}/approve",json={'plan_hash':w['plan_hash'],'ui_locale':'zh-CN','confirmation':True,'single_model_disclosed':True})
    assert approved.status_code==200,approved.text
    response=c.post(execute,json=action);assert response.status_code==202,response.text
    d=wait()
    if no_change or deterministic_fail:
        assert d['works'][-1]['state']=='FAILED'
        execution=next(e for e in d['executions'] if e['id']==response.json()['id'])
        assert execution['error_code']==('ITERATION_TEST_FAILED' if deterministic_fail else 'ITERATION_NO_CHANGES')
        if deterministic_fail:
            assert execution['evidence']['deterministic_checks']['files']
            assert execution['evidence']['validation']=='FAILED'
            assert execution['evidence']['deterministic_verification']=='FAILED'
        assert 'retain this diagnostic' in execution['output']
        assert execution['evidence']['thread_id']=='synthetic-no-change'
        assert c.post(f"/api/r2/iterations/{w['id']}/review",json={**action,'request_id':'blocked-review'}).status_code==409
        assert git('rev-parse','HEAD')==before
        assert d['request_budget']['used']==2+int(revise)
        assert not any(a['event']=='CANDIDATE_READY' for a in d['activity'])
        return
    assert d['works'][-1]['state']=='BUILT'
    assert c.post(execute,json=action).json()['id']==response.json()['id']
    assert calls==([False] if revise else [])+[False,False]
    review=c.post(f"/api/r2/iterations/{w['id']}/review",json={**action,'request_id':'synthetic-review-1'})
    assert review.status_code==202,review.text
    d=wait();assert d['works'][-1]['state']=='REVIEWED'
    assert calls==([False] if revise else [])+[False,False,False]
    assert d['request_budget']['used']==3+int(revise)
    assert git('rev-parse','HEAD')==before and git('status','--porcelain')==''
    assert d['executions'][-1]['evidence']['review_independence']=='SEPARATE_SESSION_SAME_MODEL'
    assert c.post(f"/api/r2/iterations/{w['id']}/candidate/build",json={'digest':'not-reviewed','confirmation':True,'ui_locale':'en-US'}).status_code==409
    assert c.get('/api/r2/update-status').json()['owner_accepted'] is False


def test_translation_contract_and_resource_fingerprints(product):
    import re
    from pathlib import Path
    c,_,settings=product
    root=settings.static_cockpit_dir/'project_first'
    catalog=json.loads((root/'catalog.json').read_text())
    assert all(set(pair)=={'en-US','zh-CN'} and all(pair.values()) for pair in catalog.values())
    codes=set()
    for module in ('project_first','project_sources','project_execution','iteration_studio','iteration_candidate'):
        codes.update(re.findall(r"(?:fail|SourceError|ExecutionFailure)\('([A-Z0-9_]+)'",Path('twos_runtime',module+'.py').read_text()))
    assert all('error.'+code in catalog for code in codes)
    response=c.get('/project-manager');assert response.status_code==200
    assert response.headers['cache-control']=='no-store'
    for name in ('app.js','catalog.json','styles.css'):
        assert name+'?sha256='+hashlib.sha256((root/name).read_bytes()).hexdigest() in response.text
    assert '?hash=BUILD' not in response.text


def test_recovery_epoch_cannot_reuse_prior_approval(product,monkeypatch):
    c,app,_=product;pid=project(c);team(c,pid);w=approve(c,task(c,pid))
    from twos_runtime import project_first
    monkeypatch.setattr(project_first,'recovery_epoch',lambda _: 'new-restored-authority')
    response=c.post(f"/api/r2/work/{w['id']}/start",json={'plan_hash':w['plan_hash'],'request_id':'synthetic-after-restore','confirmation':True})
    assert response.status_code==409 and response.json()['error']['code']=='RECOVERY_REPLAN_REQUIRED'
    assert c.get(f'/api/r2/projects/{pid}').json()['request_budget']['used']==0
    assert app.state.project_execution.jobs=={}


def test_missing_executable_blocks_new_call_but_preserves_projects(product,monkeypatch):
    c,app,_=product;pid=project(c);team(c,pid);w=approve(c,task(c,pid))
    monkeypatch.setattr(tool_recovery,'candidates',lambda _: [])
    assert c.get('/projects').status_code==200
    data=c.get(f'/api/r2/projects/{pid}').json()
    assert data['configuration_saved'] and data['tool_state']=='EXECUTABLE_MISSING_OR_CHANGED'
    assert data['works'][0]['plan_hash']==w['plan_hash']
    response=c.post(f"/api/r2/work/{w['id']}/start",json={'plan_hash':w['plan_hash'],'request_id':'missing-executable-case','confirmation':True})
    assert response.status_code==409
    assert app.state.project_execution.jobs=={}


def test_provider_failure_keeps_terminal_receipt_and_does_not_retry(product):
    from twos_runtime.project_execution import ExecutionFailure
    c,app,_=product;pid=project(c);team(c,pid);w=approve(c,task(c,pid));calls=[]
    def fail(*a,**kw):calls.append(1);raise ExecutionFailure('PROVIDER_REQUEST_FAILED')
    app.state.project_execution.runner=fail
    action={'plan_hash':w['plan_hash'],'request_id':'synthetic-failed-provider','confirmation':True}
    response=c.post(f"/api/r2/work/{w['id']}/start",json=action);assert response.status_code==202
    for _ in range(100):
        data=c.get(f'/api/r2/projects/{pid}').json()
        if data['works'][0]['state']=='FAILED':break
        time.sleep(.02)
    assert data['executions'][0]['error_code']=='PROVIDER_REQUEST_FAILED'
    assert c.post(f"/api/r2/work/{w['id']}/start",json=action).json()['id']==response.json()['id']
    assert len(calls)==1 and data['request_budget']['used']==1


def test_native_environment_paths_are_generated_and_isolated(tmp_path):
    from twos_runtime.desktop import directories
    original=directories(tmp_path)
    fresh=directories(tmp_path,environment_id='env_'+'a'*32)
    assert all(a!=b for a,b in zip(original,fresh))
    assert all('env_'+'a'*32 in str(p) for p in fresh)
    for value in ('../../owner','env_owner','/Applications/Tianma Work OS.app'):
        with pytest.raises(Exception):directories(tmp_path,environment_id=value)


def test_codex_adapter_process_boundary_no_real_provider(tmp_path,monkeypatch):
    import sys,threading
    from twos_runtime.project_execution import codex_document,ExecutionFailure
    executable=tmp_path/'substitute'
    executable.write_text('#!'+sys.executable+'\n'+"""
import json, os, sys
text = sys.stdin.read()
assert "OPENAI_API_KEY" not in os.environ
assert "--ignore-user-config" in sys.argv
assert "features.shell_tool=false" in sys.argv
assert "features.unbounded_connection_retries=false" in sys.argv
assert "--strict-config" in sys.argv
assert 'model_provider="twos_bounded"' in sys.argv
assert 'forced_login_method="chatgpt"' in sys.argv
assert not any(a.startswith("model_providers.openai=") for a in sys.argv)
assert any("request_max_retries=0,stream_max_retries=0,supports_websockets=false" in a for a in sys.argv)
from pathlib import Path
Path(sys.argv[sys.argv.index("--output-last-message")+1]).write_text("Synthetic boundary test only.")
print(json.dumps({"type":"thread.started","thread_id":"synthetic-session"}))
print(json.dumps({"type":"turn.started"}))
print(json.dumps({"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"Synthetic boundary test only."}}))
print(json.dumps({"type":"turn.completed","usage":{"input_tokens":0,"output_tokens":0}}))
""")
    executable.chmod(0o700);monkeypatch.setenv('OPENAI_API_KEY','synthetic-test-value')
    output,evidence=codex_document(str(executable),'synthetic','Non-sensitive test',tmp_path,threading.Event(),lambda _:None)
    assert output=='Synthetic boundary test only.' and evidence['exit_code']==0
    assert evidence['returned_model']=='NOT_REPORTED_BY_CLI'
    assert evidence['cli_invocations']==1 and evidence['provider_request_count']=='NOT_EXPOSED_BY_CLI'
    assert evidence['transport_retry_configuration']=={'request_max_retries':0,'stream_max_retries':0,'supports_websockets':False,'unbounded_connection_retries':False}
    executable.write_text('#!'+sys.executable+'\nimport time\ntime.sleep(10)\n')
    stop=threading.Event();stop.set()
    with pytest.raises(ExecutionFailure,match='EXECUTION_CANCELLED'):
        codex_document(str(executable),'synthetic','cancel',tmp_path,stop,lambda _:None)


def test_maintenance_refuses_active_project_execution(product):
    from twos_runtime.maintenance import safe_state,MaintenanceError
    c,app,settings=product;pid=project(c);w=task(c,pid)
    with app.state.session_factory() as s:
        s.add(WorkExecution(id='synthetic-running',work_id=w['id'],revision=1,phase='document',idempotency_key='test-active',plan_hash='',state='RUNNING',input_json='{}',started_at='2026-09-30T00:00:00+00:00'))
        s.commit()
    with pytest.raises(MaintenanceError) as exc:
        safe_state(settings.data_root/'twos.sqlite3')
    assert exc.value.code=='ACTIVE_OPERATION'


def test_install_identity_receipt_is_explicit_owned_and_durable(product,monkeypatch):
    from twos_runtime.project_first import save_preference
    from twos_runtime.project_first_models import ProjectActivity,ProductPreference
    from twos_runtime import desktop
    c,app,_=product;pid=project(c,'Synthetic development','development');w=task(c,pid)
    pending={'project_id':pid,'work_id':w['id'],'candidate':{'sha256':'a'*64,'source_commit':'b'*40,'build':'101.11.1'}}
    with app.state.session_factory() as s:
        save_preference(s,'pending_update',pending);s.commit()
    monkeypatch.setattr(desktop,'build_identity',lambda:{'source_commit':'b'*40,'build_version':'101.11.1','self_iteration_test_artifact':True})
    assert c.get('/api/r2/update-status').json()['installed_identity_matches']
    with app.state.session_factory() as s:
        assert s.get(ProductPreference,'installed_update:'+'a'*64) is None
    first=c.post('/api/r2/update-status/record',json={});assert first.status_code==200
    again=c.post('/api/r2/update-status/record',json={})
    assert first.json()['installed_receipt']==again.json()['installed_receipt']
    assert not first.json()['installed_receipt']['owner_accepted']
    with app.state.session_factory() as s:
        assert len(list(s.scalars(select(ProjectActivity).where(ProjectActivity.event=='CANDIDATE_INSTALLED_IDENTITY_VERIFIED'))))==1
    result=c.post(f'/api/r2/projects/{pid}/iterations',json={'body':'Another layer','output_locale':'en-US','request_id':'forbidden-grandchild','confirmation':True})
    assert result.status_code==409 and result.json()['error']['code']=='CHILD_ARTIFACT_ITERATION_DISABLED'
    assert not app.state.project_execution.jobs


def test_revision_preserves_history_and_invalidates_exact_prior_plan(product):
    from twos_runtime.project_first_models import ProjectActivity
    c,app,_=product;pid=project(c);team(c,pid);w=approve(c,task(c,pid))
    oldhash=w['plan_hash']
    payload={'title':'Revised synthetic task','body':'Changed input: explicitly identify missing weekly originals.','output_locale':'zh-CN','source_ids':[],'expected_revision':1,'request_id':'synthetic-revision-one'}
    r=c.post(f"/api/r2/work/{w['id']}/revise",json=payload);assert r.status_code==200,r.text
    assert r.json()['revision']==2 and r.json()['approval']=={} and r.json()['state']=='DRAFT'
    assert c.post(f"/api/r2/work/{w['id']}/revise",json=payload).json()==r.json()
    assert c.post(f"/api/r2/work/{w['id']}/start",json={'plan_hash':oldhash,'request_id':'stale-plan-start','confirmation':True}).status_code==409
    with app.state.session_factory() as s:
        archived=s.scalar(select(ProjectActivity).where(ProjectActivity.event=='TASK_REVISION_ARCHIVED'))
        assert json.loads(archived.content_json)['plan_hash']==oldhash
    new=approve(c,r.json());assert new['plan_hash']!=oldhash
    data=c.get(f'/api/r2/projects/{pid}').json()
    edit={'name':'Confirmed project name','goal':'Current user-confirmed read-only scope','expected_digest':data['context_digest']}
    assert c.post(f'/api/r2/projects/{pid}/edit',json=edit).status_code==200
    revised=c.get(f'/api/r2/projects/{pid}').json()
    assert revised['name']==edit['name'] and revised['works'][0]['state']=='REPLAN_REQUIRED'
    assert revised['request_budget']['used']==0 and app.state.project_execution.jobs=={}
    assert c.post(f'/api/r2/projects/{pid}/edit',json=edit).status_code==409


def test_provider_diagnostics_classified_without_persisting_raw_output(tmp_path):
    import sys,threading
    from twos_runtime.project_execution import codex_document,ExecutionFailure,classify_failure
    assert classify_failure('Error loading config.toml: reserved built-in provider IDs')=='EXECUTOR_CONFIGURATION_UNSUPPORTED'
    assert classify_failure('model is not supported')=='PROVIDER_MODEL_UNAVAILABLE'
    assert classify_failure('unexpected status 502 Bad Gateway')=='PROVIDER_CONNECTION_FAILED'
    assert classify_failure('rate limit exceeded')=='PROVIDER_ALLOWANCE_UNAVAILABLE'
    executable=tmp_path/'substitute';executable.write_text('#!'+sys.executable+'\nimport json,sys\nsys.stdin.read()\nprint(json.dumps({"type":"thread.started","thread_id":"synthetic-thread"}))\nprint(json.dumps({"type":"error","message":"error sending request with PRIVATE_SENTINEL"}))\nsys.exit(1)\n');executable.chmod(0o700)
    with pytest.raises(ExecutionFailure) as error:
        codex_document(str(executable),'synthetic','Synthetic input',tmp_path,threading.Event(),lambda _:None)
    assert error.value.code=='PROVIDER_CONNECTION_FAILED'
    assert error.value.evidence['exit_code']==1
    assert 'PRIVATE_SENTINEL' not in json.dumps(error.value.evidence)


def test_production_action_labels_do_not_claim_demo():
    from pathlib import Path
    catalog=json.loads(Path('static_cockpit/project_first/catalog.json').read_text())
    for key in ('sourcesDesc','confirmImport','approvePlan','exportMd','createDemoAccount','saveDemoTeam','startDemo'):
        for text in catalog[key].values():
            assert not any(word in text.lower() for word in ('demo','prototype','sample','演示','示例','原型'))
