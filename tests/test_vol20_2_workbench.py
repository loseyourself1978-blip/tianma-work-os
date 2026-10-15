"""20.2 behavioral gates. Synthetic SMTP/model dependencies are labelled substitutes."""
import base64
from dataclasses import replace
import json
import secrets
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from twos_runtime.app import create_app
from twos_runtime.config import Settings
from twos_runtime import tool_recovery
from twos_runtime.workbench_models import EmailChallenge, Chat, ChatMessage, EmailIdentity
from twos_runtime.models import User

PASSWORD = 'Synthetic-test-password-2026'

class MailDouble:
    def __init__(self): self.sent = []
    def available(self): return True
    def send(self, email, purpose, code): self.sent.append((email, purpose, code))

@pytest.fixture
def wb(tmp_path, monkeypatch):
    settings = Settings(database_url=f'sqlite:///{tmp_path}/test.db', data_root=tmp_path)
    monkeypatch.setattr(tool_recovery, 'candidates', lambda _: [{'id': 'test-tool', 'path': '/synthetic/codex'}])
    app = create_app(settings, start_scheduler=False)
    mail = MailDouble(); app.state.mail_sender = mail
    with TestClient(app) as client:
        yield client, app, mail, settings


def begin(c, purpose='signup', email='synthetic@example.test'):
    r = c.post('/api/auth/email/begin', json={'email': email, 'purpose': purpose, 'password': PASSWORD, 'confirmation': True})
    assert r.status_code == 200, r.text
    return r.json()['challenge_id']


def verify(c, cid, mail, purpose='signup', code=None):
    return c.post('/api/auth/email/verify', json={'challenge_id': cid, 'purpose': purpose, 'code': code or mail.sent[-1][2]})


def account(wb):
    c, app, mail, _ = wb; cid = begin(c)
    assert verify(c, cid, mail).status_code == 200
    return c


def connected(wb):
    c = account(wb); _, app, _, _ = wb
    from twos_runtime.project_first import save_preference
    with app.state.session_factory() as s:
        user = s.scalar(select(User))
        save_preference(s, 'wb:connection:'+str(user.id), {'tool_id': 'test-tool', 'executable': '/synthetic/codex', 'model': 'synthetic-model'})
        s.commit()
    app.state.discussion.runner = lambda *args, **kwargs: ('Synthetic response to '+args[2][-50:], {'test_double': True, 'provider_calls': 0})
    return c


def chat(c):
    r = c.post('/api/r2/wb/chats', json={'request_id': secrets.token_hex(16)})
    assert r.status_code == 201, r.text
    return r.json()['id']


def send(c, cid, body='Synthetic question', **extra):
    return c.post(f'/api/r2/wb/chats/{cid}/send', json={'body': body, 'request_id': secrets.token_hex(16), **extra})


def wait(c, cid):
    for _ in range(100):
        d = c.get(f'/api/r2/wb/chats/{cid}').json()
        if not any(m['state'] in ('QUEUED', 'RUNNING') for m in d['messages']): return d
        time.sleep(.02)
    pytest.fail('discussion did not settle')


def test_verified_signup_empty_and_legacy_boundary(wb):
    c = account(wb)
    assert c.get('/api/r2/projects').json() == []
    assert c.get('/api/r2/wb/state').json()['chats'] == []
    assert c.get('/api/projects').status_code == 403
    assert c.get('/api/auth/session').json()['authenticated']
    assert c.post('/api/auth/logout').status_code == 200
    assert c.get('/api/r2/wb/state').status_code == 401
    assert c.post('/api/auth/email/login', json={'email':'synthetic@example.test','password':PASSWORD}).status_code == 200


def test_challenge_wrong_purpose_session_attempt_limit_and_no_plaintext(wb):
    c, app, mail, _ = wb; cid = begin(c); code = mail.sent[-1][2]
    assert verify(c, cid, mail, purpose='reset').status_code == 400
    with TestClient(app) as stranger:
        assert verify(stranger, cid, mail).status_code == 400
    bad = '000000' if code != '000000' else '999999'
    for _ in range(5): assert verify(c, cid, mail, code=bad).status_code == 400
    assert verify(c, cid, mail).status_code == 400
    with app.state.session_factory() as s:
        row = s.get(EmailChallenge, cid)
        assert row.state == 'LOCKED' and row.attempts == 5
        assert row.code_hash != code and row.password_hash != PASSWORD
        assert s.scalar(select(User)) is None


def test_expired_and_one_time_proof(wb):
    c, app, mail, _ = wb; cid = begin(c)
    with app.state.session_factory() as s:
        s.get(EmailChallenge, cid).expires = 1; s.commit()
    assert verify(c, cid, mail).status_code == 400
    with app.state.session_factory() as s:
        s.get(EmailChallenge, cid).expires = int(time.time())+60; s.commit()
    assert verify(c, cid, mail).status_code == 200
    assert verify(c, cid, mail).status_code == 400


def test_resend_replaces_code_and_rate_limit(wb):
    c, app, mail, _ = wb; cid = begin(c); old = mail.sent[-1][2]
    assert c.post('/api/auth/email/resend',json={'challenge_id':cid}).status_code == 429
    with app.state.session_factory() as s:
        s.get(EmailChallenge, cid).issued -= 31; s.commit()
    assert c.post('/api/auth/email/resend',json={'challenge_id':cid}).status_code == 200
    if old != mail.sent[-1][2]: assert verify(c,cid,mail,code=old).status_code == 400
    assert verify(c,cid,mail).status_code == 200


def test_reset_grant_replay_and_revoked_sessions(wb):
    c = account(wb); _, app, mail, _ = wb
    old_cookies = dict(c.cookies)
    # Purpose-specific cooldown is intentionally shared to bound email volume.
    from twos_runtime.workbench_models import AuthThrottle
    with app.state.session_factory() as s:
        for row in s.scalars(select(AuthThrottle)): row.window -= 1
        s.commit()
    cid = begin(c, 'reset')
    assert verify(c,cid,mail,'reset').json()['state'] == 'RESET_AUTHORIZED'
    body={'challenge_id':cid,'password':PASSWORD+'changed','confirmation':PASSWORD+'changed'}
    assert c.post('/api/auth/email/reset',json=body).status_code == 200
    assert c.post('/api/auth/email/reset',json=body).status_code == 400
    with TestClient(app) as other:
        other.cookies.update(old_cookies)
        assert other.get('/api/r2/wb/state').status_code == 401
    assert c.post('/api/auth/email/login',json={'email':'synthetic@example.test','password':PASSWORD}).status_code == 401
    assert c.post('/api/auth/email/login',json={'email':'synthetic@example.test','password':PASSWORD+'changed'}).status_code == 200


def test_mail_unconfigured_and_failure_never_verifies(wb):
    c, app, mail, _ = wb
    mail.available = lambda: False
    assert c.post('/api/auth/email/begin',json={'email':'synthetic@example.test','purpose':'signup','password':PASSWORD,'confirmation':True}).status_code == 503
    mail.available = lambda: True
    mail.send = lambda *args: (_ for _ in ()).throw(RuntimeError('secret transport error'))
    r = c.post('/api/auth/email/begin',json={'email':'synthetic@example.test','purpose':'signup','password':PASSWORD,'confirmation':True})
    assert r.status_code == 503 and 'secret' not in r.text
    with app.state.session_factory() as s:
        assert s.scalar(select(User)) is None
        assert s.scalar(select(EmailChallenge)).state == 'SEND_FAILED'


def test_unconnected_draft_survives_restart_and_assign_without_replay(wb):
    c = account(wb); _, app, _, settings = wb; cid = chat(c)
    assert c.post(f'/api/r2/wb/chats/{cid}/draft',json={'body':'完整的原始想法\n第二行','version':0}).status_code == 200
    assert send(c,cid).status_code == 409
    pid = c.post('/api/r2/wb/projects',json={'name':'Owner chosen project','request_id':'create-project-1'}).json()['id']
    assert c.post(f'/api/r2/wb/chats/{cid}/assign',json={'project_id':pid,'confirmation':True}).json()['model_requests'] == 0
    with TestClient(create_app(settings,start_scheduler=False)) as restarted:
        restarted.cookies.update(dict(c.cookies))
        d = restarted.get(f'/api/r2/wb/chats/{cid}').json()
        assert d['draft'] == '完整的原始想法\n第二行' and d['project_id'] == pid
        assert d['messages'] == []


def test_real_service_boundary_multiturn_and_send_dedup(wb):
    c = connected(wb); _, app, _, _ = wb; cid = chat(c); calls=[]
    def model(*args, **kwargs):
        calls.append((args[2],kwargs)); return 'Synthetic contextual reply '+str(len(calls)), {'test_double':True}
    app.state.discussion.runner = model
    payload={'body':'Remember synthetic cedar seven','request_id':'request-once'}
    url=f'/api/r2/wb/chats/{cid}/send'
    assert c.post(url,json=payload).status_code == 202
    assert c.post(url,json=payload).status_code == 202
    wait(c,cid)
    assert c.post(url,json={**payload,'body':'different'}).status_code == 409
    assert send(c,cid,'What did I ask?').status_code == 202
    d=wait(c,cid)
    assert len(calls)==2 and 'cedar seven' in calls[1][0] and 'reply 1' in calls[1][0]
    assert len(d['messages'])==4 and all(not options['write'] for _,options in calls)
    assert c.get('/api/r2/projects').json()==[]


def test_attachment_consent_and_foreign_chat_boundary(wb):
    c=connected(wb); cid=chat(c); other=chat(c); calls=[]
    def model(*args, **kwargs):
        calls.append(args[2]); return 'Synthetic content acknowledged', {'test_double':True}
    wb[1].state.discussion.runner=model
    r=c.post(f'/api/r2/wb/chats/{cid}/attachments',json={'filename':'note.md','data_base64':base64.b64encode(b'Content: orchid 29').decode()})
    assert r.status_code==201
    aid=r.json()['id']
    assert c.get(f'/api/r2/wb/chats/{other}/attachments/{aid}').status_code==404
    assert send(c,cid,attachments=[aid]).status_code==409
    assert send(c,cid,attachments=[aid],send_selected_content=True).status_code==202
    d=wait(c,cid); assert len(calls)==1 and 'Content: orchid 29' in calls[0]
    assert d['messages'][-1]['evidence']['attachments'][0]['id']==aid
    assert send(c,other,attachments=[aid],send_selected_content=True).status_code==404


def test_images_reach_adapter_in_private_working_directory(wb):
    from pathlib import Path
    c=connected(wb); cid=chat(c); calls=[]
    samples={'a.png':b'\x89PNG\r\n\x1a\nsynthetic','b.jpg':b'\xff\xd8\xffsynthetic'}
    ids=[]
    for name,data in samples.items():
        r=c.post(f'/api/r2/wb/chats/{cid}/attachments',json={'filename':name,'data_base64':base64.b64encode(data).decode()})
        assert r.status_code==201; ids.append(r.json()['id'])
    def adapter(executable,model,prompt,cwd,cancel,spawned,**options):
        assert isinstance(cwd,Path) and cwd.is_dir()
        assert cwd.is_relative_to(wb[3].data_root/'discussion-work')
        assert not cwd.stat().st_mode & 0o077
        assert options['write'] is False
        assert {p.read_bytes() for p in options['image_paths']}==set(samples.values())
        assert all(p.parent==cwd and not p.stat().st_mode & 0o077 for p in options['image_paths'])
        calls.append(1); return 'Synthetic image adapter receipt',{'test_double':True,'provider_invocations':0}
    wb[1].state.discussion.runner=adapter
    assert send(c,cid,'Describe the selected images',attachments=ids,send_selected_content=True).status_code==202
    d=wait(c,cid)
    assert d['messages'][-1]['state']=='COMPLETED' and calls==[1]


def test_draft_optimistic_write_rejects_late_save(wb):
    c=account(wb); cid=chat(c);url=f'/api/r2/wb/chats/{cid}/draft'
    assert c.post(url,json={'body':'new','version':0}).status_code==200
    assert c.post(url,json={'body':'late old','version':0}).status_code==409
    assert c.get(f'/api/r2/wb/chats/{cid}').json()['draft']=='new'


def test_cancel_no_automatic_replay(wb):
    c=connected(wb);_,app,_,_=wb;cid=chat(c);calls=[]
    def model(exe,model,prompt,cwd,cancel,spawned,**kwargs):
        calls.append(1)
        assert cancel.wait(5)
        return 'late reply',{}
    app.state.discussion.runner=model
    assert send(c,cid).status_code==202
    assert c.post(f'/api/r2/wb/chats/{cid}/cancel',json={}).status_code==200
    d=wait(c,cid)
    assert len(calls)==1 and d['messages'][-1]['state']=='CANCELLED'
    assert not d['messages'][-1]['body']


def test_production_workbench_assets_and_default_entry(wb):
    import hashlib
    from pathlib import Path
    c, _, _, settings = wb
    page = c.get('/projects')
    assert page.status_code == 200 and str(page.url).endswith('/workbench')
    assert page.headers['cache-control'] == 'no-store'
    root = settings.static_cockpit_dir/'workbench'
    for name in ('app.js','styles.css','catalog.json'):
        assert name+'?'+hashlib.sha256((root/name).read_bytes()).hexdigest() in page.text
    script = (root/'app.js').read_text()
    assert 'localStorage' not in script and 'demoAccounts' not in script
    assert 'e.isComposing' in script and 'e.keyCode!==229' in script


def test_chat_creation_identity_survives_assignment(wb):
    c=account(wb); body={'request_id':'immutable-chat-identity'}
    cid=c.post('/api/r2/wb/chats',json=body).json()['id']
    pid=c.post('/api/r2/wb/projects',json={'name':'Synthetic project','request_id':'immutable-project'}).json()['id']
    assert c.post(f'/api/r2/wb/chats/{cid}/assign',json={'project_id':pid,'confirmation':True}).status_code==200
    assert c.post('/api/r2/wb/chats',json=body).json()['id']==cid
    assert c.post('/api/r2/wb/chats',json={**body,'project_id':pid}).status_code==409


def test_selected_source_search_is_explicit_retained_and_account_scoped(wb):
    c=connected(wb); cid=chat(c); calls=[]
    wb[1].state.discussion.runner=lambda *args,**kwargs:(calls.append(args[2]) or 'Synthetic searched reply', {'test_double':True})
    pid=c.post('/api/r2/wb/projects',json={'name':'Synthetic source project','request_id':'source-project-once'}).json()['id']
    c.post(f'/api/r2/wb/chats/{cid}/assign',json={'project_id':pid,'confirmation':True})
    preview=c.post(f'/api/r2/projects/{pid}/imports/preview',json={'filename':'fixture.txt','data_base64':base64.b64encode(b'Unselected private line\nSelected cobalt 37').decode()}).json()
    assert c.post(f"/api/r2/projects/{pid}/imports/{preview['preview_id']}/confirm",json={'sha256':preview['sha256'],'names':['fixture.txt'],'confirmation':True}).status_code==200
    sid=c.get(f'/api/r2/projects/{pid}').json()['sources'][0]['id']
    r=c.post(f'/api/r2/wb/chats/{cid}/draft',json={'body':'Find the selected detail','version':0,'source_ids':[sid],'search':'cobalt'})
    assert r.status_code==200 and calls==[]
    assert c.get(f'/api/r2/wb/chats/{cid}').json()['draft_tool']=={'source_ids':[sid],'search':'cobalt'}
    assert send(c,cid,source_ids=[sid],search='cobalt').status_code==409 and calls==[]
    assert send(c,cid,source_ids=[sid],search='cobalt',send_selected_content=True).status_code==202
    d=wait(c,cid)
    assert len(calls)==1 and 'Selected cobalt 37' in calls[0] and 'Unselected private line' not in calls[0]
    assert d['messages'][-1]['evidence']['tool_receipt']['results'][0]['line']==2
    assert send(c,chat(c),source_ids=[sid],search='cobalt',send_selected_content=True).status_code==422


def test_email_accounts_do_not_inherit_other_account_project_chat_or_attachment(wb):
    c=account(wb); cid=chat(c)
    pid=c.post('/api/r2/wb/projects',json={'name':'Private test project','request_id':'private-project'}).json()['id']
    aid=c.post(f'/api/r2/wb/chats/{cid}/attachments',json={'filename':'private.txt','data_base64':base64.b64encode(b'Private synthetic source').decode()}).json()['id']
    c.post('/api/auth/logout')
    challenge=begin(c,email='second@example.test'); assert verify(c,challenge,wb[2]).status_code==200
    assert c.get('/api/r2/projects').json()==[] and c.get('/api/r2/wb/state').json()['chats']==[]
    for path in [f'/api/r2/projects/{pid}',f'/api/r2/wb/chats/{cid}',f'/api/r2/wb/chats/{cid}/attachments/{aid}']:
        assert c.get(path).status_code==404
    assert c.post(f'/api/r2/wb/projects/{pid}/open',json={'confirmation':True}).status_code==404


def test_email_provider_usage_is_account_scoped_without_twos_cap(wb):
    from twos_runtime.project_first import save_preference, preference
    from tests.test_vol20_r2_project_first import task, approve
    c=account(wb); app=wb[1]
    with app.state.session_factory() as s:
        save_preference(s,'provider_budget',{'limit':8,'used':4}); s.commit()
    ids=[]
    for index in range(2):
        if index:
            c.post('/api/auth/logout')
            challenge=begin(c,email='budget-second@example.test')
            assert verify(c,challenge,wb[2]).status_code==200
        pid=c.post('/api/r2/wb/projects',json={'name':'Budget account '+str(index),'request_id':'budget-'+str(index)}).json()['id']
        ids.append(pid)
        config={'tool_id':'test-tool','planner':'synthetic-model','executor':'synthetic-model','reviewer':'synthetic-model','request_limit':index+1,'existing_plan_only':True,'human_gates':[]}
        # Owner removed the ten-call cap; legacy client fields no longer limit usage.
        assert c.post(f'/api/r2/projects/{pid}/team',json={**config,'request_limit':11}).status_code==200
        assert c.post(f'/api/r2/projects/{pid}/team',json=config).status_code==200
        assert c.get(f'/api/r2/projects/{pid}').json()['request_budget']=={'limit':None,'used':0}
    app.state.project_execution.runner=lambda *args,**kwargs: ('Synthetic budget check',{'test_double':True,'provider_invocations':0})
    w=approve(c,task(c,ids[1]))
    r=c.post(f"/api/r2/work/{w['id']}/start",json={'plan_hash':w['plan_hash'],'request_id':'budget-execution-once','confirmation':True})
    assert r.status_code==202,r.text
    for _ in range(100):
        d=c.get(f'/api/r2/projects/{ids[1]}').json()
        if d['executions'][0]['state']=='COMPLETED': break
        time.sleep(.02)
    assert d['executions'][0]['state']=='COMPLETED'
    assert d['request_budget']=={'limit':None,'used':1}
    c.post('/api/auth/logout')
    assert c.post('/api/auth/email/login',json={'email':'synthetic@example.test','password':PASSWORD}).status_code==200
    assert c.get(f'/api/r2/projects/{ids[0]}').json()['request_budget']=={'limit':None,'used':0}
    with app.state.session_factory() as s:
        assert preference(s,'provider_budget')=={'limit':8,'used':4}


def test_additive_10126_upgrade_snapshots_and_keeps_authority_and_owner_data(tmp_path):
    import sqlite3
    from tests.test_vol19_fresh_install_first_run import fresh_settings, create_owner_and_workspace, finish_setup
    from twos_runtime.maintenance import Maintenance, verify_preserved_data, inspect_database
    settings=fresh_settings(tmp_path)
    with TestClient(create_app(settings,start_scheduler=False)) as c:
        create_owner_and_workspace(c,settings,tmp_path/'workspace');finish_setup(c)
        cookies=dict(c.cookies)
    service=Maintenance(settings)
    with sqlite3.connect(service.db) as db:
        names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'wb_%'")]
        for name in names: db.execute('DROP TABLE "'+name+'"')
        db.execute("DELETE FROM schema_versions WHERE version='vol20.002'")
    assert inspect_database(service.db)['schema']=='vol20.001'
    with TestClient(create_app(settings,start_scheduler=False)) as c:
        c.cookies.update(cookies)
        assert c.get('/api/auth/session').json()['authenticated']
        assert c.get('/api/r2/wb/state').status_code==200
        assert c.get('/api/setup/status').json()['state']=='ready'
    assert service.journal()['state']=='MIGRATION_COMPLETE'
    assert service.authority()=={}
    assert inspect_database(service.db)['schema']=='vol20.002'
    verify_preserved_data(service.root/'prior.sqlite3',service.db,allow_seed_rows=False)


@pytest.mark.parametrize('existing_owner',[False,True])
def test_email_user_restarts_packaged_fresh_install_without_changing_legacy_owner(tmp_path,existing_owner):
    from tests.test_vol19_fresh_install_first_run import fresh_settings,create_owner_and_workspace,finish_setup
    settings=fresh_settings(tmp_path); app=create_app(settings,start_scheduler=False);mail=MailDouble();app.state.mail_sender=mail
    with TestClient(app) as c:
        if existing_owner:
            create_owner_and_workspace(c,settings,tmp_path/'workspace');finish_setup(c)
            c.post('/api/auth/logout')
        challenge=begin(c);assert verify(c,challenge,mail).status_code==200
        pid=c.post('/api/r2/wb/projects',json={'name':'Email-owned project','request_id':'email-owned-project'}).json()['id']
        cookies=dict(c.cookies)
    with TestClient(create_app(settings,start_scheduler=False)) as c:
        c.cookies.update(cookies)
        assert c.get('/api/r2/wb/state').status_code==200
        assert c.get('/api/r2/projects').json()[0]['id']==pid
        assert c.get('/api/projects').status_code in (403,428)
        with c.app.state.session_factory() as s:
            from twos_runtime.models import Installation
            installation=s.scalar(select(Installation))
            assert bool(installation.owner_user_id)==existing_owner
            if existing_owner:
                from twos_runtime.security import legacy_owner_candidates
                assert [u.id for u in legacy_owner_candidates(s,installation.owner_user_id)]==[installation.owner_user_id]


@pytest.mark.parametrize('transport_fails',[False,True])
def test_late_smtp_completion_cannot_reactivate_replaced_challenge(wb,transport_fails):
    c,app,mail,_=wb
    def replacement(*args):
        with app.state.session_factory() as s:
            row=s.scalar(select(EmailChallenge))
            row.state='REPLACED';row.code_hash='replacement-proof';s.commit()
        if transport_fails:raise OSError('synthetic mail failure')
    mail.send=replacement
    result=c.post('/api/auth/email/begin',json={'email':'synthetic@example.test','purpose':'signup','password':PASSWORD,'confirmation':True})
    assert result.status_code in (409,503)
    with app.state.session_factory() as s:
        row=s.scalar(select(EmailChallenge))
        assert row.state=='REPLACED' and row.code_hash=='replacement-proof'
        assert s.scalar(select(User)) is None


def test_portable_backup_excludes_email_proofs_and_reset_grants(wb,tmp_path):
    import sqlite3
    from sqlalchemy.engine import make_url
    from twos_runtime.maintenance import snapshot
    c,app,mail,settings=wb
    cid=begin(c)
    target=tmp_path/'portable.sqlite3'
    snapshot(__import__('pathlib').Path(make_url(settings.database_url).database),target,remove_sessions=True)
    with sqlite3.connect(target) as db:
        assert db.execute('SELECT COUNT(*) FROM wb_email_challenges').fetchone()[0]==0
        assert db.execute('SELECT COUNT(*) FROM session_tokens').fetchone()[0]==0
    # Creating the backup did not invalidate the active browser's proof.
    assert verify(c,cid,mail).status_code==200


def test_existing_project_explicit_development_enable_retains_chat_and_target_gates(wb, tmp_path):
    from twos_runtime.iteration_studio import git, CATALOG
    from twos_runtime.project_first_models import WorkItem, WorkExecution, ProjectActivity
    c = account(wb); _, app, _, _ = wb
    pid = c.post('/api/r2/wb/projects', json={'name':'Existing ordinary project','request_id':'enable-existing-001'}).json()['id']
    cid = chat(c)
    c.post(f'/api/r2/wb/chats/{cid}/assign', json={'project_id':pid,'confirmation':True})
    c.post(f'/api/r2/wb/chats/{cid}/draft', json={'body':'Preserved draft','attachments':[],'version':0})
    source = tmp_path.parent/(tmp_path.name+'-public-source'); source.mkdir()
    for name, body in {CATALOG:json.dumps({'noSourcesDesc':{'en-US':'Original guidance','zh-CN':'原始提示文案'}}), 'twos_runtime/app.py':'# synthetic', 'scripts/build_macos.py':'# synthetic'}.items():
        path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body)
    for args in [('init','-b','main'),('add','.'),('commit','-m','Synthetic public source')]:
        git(source,'-c','user.name=Fixture','-c','user.email=fixture@example.test',*args)
    endpoint=f'/api/r2/projects/{pid}/target'
    r=c.post(endpoint+'/preview',json={'path':str(source)})
    assert r.status_code==409 and 'DEVELOPMENT_PROJECT_REQUIRED' in r.text
    enable=f'/api/r2/wb/projects/{pid}/enable-development'
    assert c.post(enable,json={'confirmation':False}).status_code==422
    for _ in range(2):
        r=c.post(enable,json={'confirmation':True})
        assert r.status_code==200 and r.json()['model_requests']==0
    assert c.get(f'/api/r2/projects/{pid}').json()['kind']=='development'
    preview=c.post(endpoint+'/preview',json={'path':str(source)})
    assert preview.status_code==200,preview.text
    r=c.post(endpoint+'/confirm',json={'preview_hash':preview.json()['preview_hash'],'confirmation':True})
    assert r.status_code==200,r.text
    assert c.get(f'/api/r2/wb/chats/{cid}').json()['draft']=='Preserved draft'
    assert git(source,'status','--porcelain')==''
    with app.state.session_factory() as s:
        assert not list(s.scalars(select(WorkItem))) and not list(s.scalars(select(WorkExecution)))
        assert len(list(s.scalars(select(ProjectActivity).where(ProjectActivity.event=='DEVELOPMENT_ENABLED'))))==1
    c.post('/api/auth/logout')
    assert verify(c,begin(c,email='second@example.test'),wb[2]).status_code==200
    assert c.post(enable,json={'confirmation':True}).status_code==404


def test_chat_delete_restore_preserves_data_and_never_replays(wb):
    from twos_runtime.workbench_models import ChatAttachment, ChatHandoff
    from twos_runtime.project_first_models import WorkItem
    c=connected(wb);_,app,_,_=wb;cid=chat(c)
    assert send(c,cid).status_code==202
    before=wait(c,cid);calls=[]
    app.state.discussion.runner=lambda *a,**k: calls.append(True)
    c.post(f'/api/r2/wb/chats/{cid}/draft',json={'body':'Keep draft','attachments':[],'version':before['draft_version']})
    c.post('/api/r2/wb/layout',json={'chat_id':cid})
    assert c.post(f'/api/r2/wb/chats/{cid}/delete',json={'confirmation':False}).status_code==422
    for _ in range(2): assert c.post(f'/api/r2/wb/chats/{cid}/delete',json={'confirmation':True}).status_code==200
    state=c.get('/api/r2/wb/state').json()
    assert state['chats']==[] and state['deleted_chats'][0]['id']==cid and state['layout']['chat_id'] is None
    assert c.get(f'/api/r2/wb/chats/{cid}').status_code==410
    assert send(c,cid).status_code==410
    assert c.post(f'/api/r2/wb/chats/{cid}/draft',json={'body':'Overwrite','attachments':[],'version':before['draft_version']+1}).status_code==410
    c.post('/api/auth/logout')
    assert verify(c,begin(c,email='stranger@example.test'),wb[2]).status_code==200
    assert c.post(f'/api/r2/wb/chats/{cid}/restore',json={'confirmation':True}).status_code==404
    assert c.post(f'/api/r2/wb/chats/{cid}/delete',json={'confirmation':True}).status_code==404
    c.post('/api/auth/logout');c.post('/api/auth/email/login',json={'email':'synthetic@example.test','password':PASSWORD})
    for _ in range(2): assert c.post(f'/api/r2/wb/chats/{cid}/restore',json={'confirmation':True}).status_code==200
    restored=c.get(f'/api/r2/wb/chats/{cid}').json()
    assert restored['messages']==before['messages'] and restored['draft']=='Keep draft'
    assert c.get('/api/r2/wb/state').json()['deleted_chats']==[] and not calls


@pytest.mark.parametrize('busy_kind',['discussion','execution'])
def test_chat_delete_rejects_active_work(wb,busy_kind):
    from twos_runtime.project_first_models import WorkItem,WorkExecution
    from twos_runtime.workbench_models import ChatHandoff
    c=account(wb);_,app,_,_=wb;cid=chat(c)
    pid=c.post('/api/r2/wb/projects',json={'name':'Retained project','request_id':'busy-project-001'}).json()['id']
    with app.state.session_factory() as s:
        if busy_kind=='discussion':
            s.add(ChatMessage(id='busy-message',chat_id=cid,request_id='busy',role='assistant',body='',state='QUEUED',created_at='fixture'))
        else:
            s.add(WorkItem(id='busy-work',project_id=pid,title='Keep work',body='Synthetic',kind='document',output_locale='en-US',sources_json='[]',created_at='fixture'));s.flush()
            s.add(ChatHandoff(id='busy-handoff',chat_id=cid,work_id='busy-work',input_hash='fixture',snapshot_json='{}',created_at='fixture'))
            s.add(WorkExecution(id='busy-exec',work_id='busy-work',revision=1,phase='executor',idempotency_key='fixture',plan_hash='fixture',state='RUNNING',input_json='{}',started_at='fixture'))
        s.commit()
    r=c.post(f'/api/r2/wb/chats/{cid}/delete',json={'confirmation':True})
    assert r.status_code==409 and 'CHAT_BUSY' in r.text
    assert c.get('/api/r2/wb/state').json()['deleted_chats']==[]
    with app.state.session_factory() as s:
        if busy_kind=='discussion':s.get(ChatMessage,'busy-message').state='CANCELLED'
        else:s.get(WorkExecution,'busy-exec').state='CANCELLED'
        s.commit()
    assert c.post(f'/api/r2/wb/chats/{cid}/delete',json={'confirmation':True}).status_code==200
    assert c.post(f'/api/r2/wb/chats/{cid}/restore',json={'confirmation':True}).status_code==200
    if busy_kind=='execution':
        d=c.get(f'/api/r2/wb/chats/{cid}').json()
        assert len(d['handoffs'])==1 and d['handoffs'][0]['executions'][0]['state']=='CANCELLED'
        assert len(d['messages'])==1
        assert c.get(f'/api/r2/wb/chats/{cid}').json()['messages']==d['messages']
