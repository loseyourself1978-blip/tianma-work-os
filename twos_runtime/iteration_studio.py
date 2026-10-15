"""Single-page controlled iteration on an explicitly selected source snapshot.

First production scope is deliberately narrow: bilingual empty-project guidance.
Candidate code never replaces the running controller or its policy/database.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
from fastapi import Depends, Request
from pydantic import Field
from sqlalchemy import select,text
from .project_first import (Strict,WorkIn,StartIn,owned,work_owned,mutation,fail,now,digest,encoded,
                           identity,preference,save_preference,activity,work_out,execution_out,recovery_epoch,provider_budget_key)
from .project_first_models import ProjectSpace,WorkItem,WorkExecution
from . import tool_recovery

CATALOG='static_cockpit/project_first/catalog.json'
REGRESSION='tests/test_vol20_r2_empty_guidance.py'
ALLOWED=(CATALOG,REGRESSION)
PATCH_SCHEMA='twos.iteration.patch.v1'


def apply_structured_patch(root,baseline,output):
    """Apply only the approved catalog value/test returned by a read-only model.

    No model-controlled path, command, Git operation, or controller write exists.
    Stage both files before mutation; rejected responses remain execution evidence.
    """
    from .iteration_contract import parse
    try:value=parse(output,'executor')
    except (ValueError,TypeError):fail('ITERATION_PATCH_FORMAT_INVALID')
    root=Path(root)
    if root.is_symlink() or any(p.is_symlink() for p in root.parents):fail('DEVELOPMENT_PATH_UNSAFE')
    for name in ALLOWED:
        p=root/name
        if any(x.is_symlink() for x in (p,*p.parents)):fail('DEVELOPMENT_PATH_UNSAFE')
    if git(root,'rev-parse','HEAD').strip()!=baseline or git(root,'status','--porcelain').strip():fail('DEVELOPMENT_SOURCE_DIRTY')
    catalog=root/CATALOG;test=root/REGRESSION
    original=catalog.read_bytes()
    if catalog.stat().st_nlink!=1 or test.exists():fail('ITERATION_SCOPE_VIOLATION')
    if value['baseline']!=baseline or value['catalog_sha256']!=hashlib.sha256(original).hexdigest():fail('DEVELOPMENT_TARGET_CHANGED')
    replacement=value['replacement'];regression=value['regression']
    if not isinstance(replacement,dict) or set(replacement)!={'en-US','zh-CN'} or any(not isinstance(s,str) or not 5<=len(s)<=500 for s in replacement.values()):fail('ITERATION_TRANSLATION_INVALID')
    if not isinstance(regression,str) or not 30<=len(regression)<=12000 or any(k not in regression for k in ('noSourcesDesc','en-US','zh-CN')):fail('ITERATION_REGRESSION_REQUIRED')
    try:compile(regression,REGRESSION,'exec')
    except (SyntaxError,ValueError):fail('ITERATION_REGRESSION_INVALID')
    if not value['summary'].strip() or len(value['summary'])>2000:fail('ITERATION_PATCH_FORMAT_INVALID')
    data=json.loads(original)
    verify_catalog_delta(data,{**data,'noSourcesDesc':replacement})
    data['noSourcesDesc']=replacement
    updated=(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode()
    # The isolated source is controller-owned; the model has read-only access.
    # Failed writes are never promoted to BUILT or approved for review.
    with tempfile.TemporaryDirectory(prefix='.twos-patch-',dir=root.parent) as staging:
        stage=Path(staging);(stage/'catalog').write_bytes(updated);(stage/'test').write_text(regression)
        (stage/'original').write_bytes(original)
        if catalog.read_bytes()!=original or test.exists():fail('DEVELOPMENT_TARGET_CHANGED')
        replaced=False
        try:
            test.parent.mkdir(parents=True,exist_ok=True)
            os.replace(stage/'catalog',catalog);replaced=True
            # Exclusive creation cannot overwrite a concurrently created test.
            os.link(stage/'test',test)
        except OSError:
            if replaced and catalog.read_bytes()==updated:os.replace(stage/'original',catalog)
            fail('ITERATION_PATCH_WRITE_FAILED')
    return {'channel':'STRUCTURED_PATCH_V1','model_filesystem_write':False,
            'baseline':baseline,'catalog_before_sha256':value['catalog_sha256'],
            'response_sha256':hashlib.sha256(output.encode()).hexdigest(),'scope':list(ALLOWED)}


def executed_regression(session,w,root,baseline):
    checks=check_changes(root,baseline)
    rows=list(session.scalars(select(WorkExecution).where(WorkExecution.work_id==w.id,
        WorkExecution.revision==w.revision,WorkExecution.phase=='executor',WorkExecution.state=='COMPLETED')))
    for row in reversed(rows):
        evidence=json.loads(row.evidence_json)
        if (row.plan_hash==w.plan_hash and evidence.get('deterministic_checks',{}).get('files')==checks['files']
                and evidence.get('regression',{}).get('passed') and evidence['regression'].get('tests_run',0)>0):
            return {'executor_id':row.id,'plan_hash':w.plan_hash,'files':checks['files'],'regression':evidence['regression']}
    fail('ITERATION_TEST_EVIDENCE_REQUIRED')


def git(path,*args):
    env={k:os.environ[k] for k in ('HOME','PATH','TMPDIR','LANG') if k in os.environ}
    env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_TERMINAL_PROMPT='0',GIT_OPTIONAL_LOCKS='0')
    r=subprocess.run(['git','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',*args],cwd=path,env=env,capture_output=True,timeout=40)
    if r.returncode: fail('DEVELOPMENT_GIT_FAILED')
    return r.stdout.decode('utf-8')


def source_identity(path,settings):
    p=Path(path).expanduser()
    if not p.is_absolute() or '..' in p.parts or any(x.is_symlink() for x in (p,*p.parents)):fail('DEVELOPMENT_PATH_UNSAFE')
    p=p.resolve(strict=True)
    protected=[settings.data_root,settings.runtime_environment,settings.log_directory]
    protected+=[Path('/Applications'),Path.home()/'Applications',Path.home()/'.codex']
    if any(p.is_relative_to(x.resolve(strict=False)) or x.resolve(strict=False).is_relative_to(p) for x in protected if x):fail('DEVELOPMENT_PATH_UNSAFE')
    if not (p/'.git').is_dir() or (p/'.git').is_symlink():fail('DEVELOPMENT_REPOSITORY_REQUIRED')
    if git(p,'rev-parse','--show-toplevel').strip()!=str(p):fail('DEVELOPMENT_PATH_UNSAFE')
    if git(p,'status','--porcelain').strip():fail('DEVELOPMENT_SOURCE_DIRTY')
    commit=git(p,'rev-parse','HEAD').strip()
    names=git(p,'ls-tree','-r','--name-only',commit).splitlines()
    for n in ('twos_runtime/app.py',CATALOG,'scripts/build_macos.py'):
        if n not in names:fail('TWOS_SOURCE_REQUIRED')
    st=p.stat()
    return {'path':str(p),'commit':commit,'device':st.st_dev,'inode':st.st_ino,
            'catalog_sha256':hashlib.sha256((p/CATALOG).read_bytes()).hexdigest()}


def isolated_target(settings,project_id):
    root=settings.data_root or Path(settings.database_url.removeprefix('sqlite:///')).parent
    return root/'development-targets'/str(project_id)


def check_changes(path,baseline):
    before=json.loads(git(path,'show',baseline+':'+CATALOG))
    after=json.loads((path/CATALOG).read_text())
    verification=verify_catalog_delta(before,after)
    changed=['noSourcesDesc']
    paths=set(git(path,'diff','--name-only',baseline).splitlines())|set(git(path,'ls-files','--others','--exclude-standard').splitlines())
    if paths!=set(ALLOWED):fail('ITERATION_SCOPE_VIOLATION')
    for name in paths:
        p=path/name
        if p.is_symlink() or not p.is_file():fail('ITERATION_SCOPE_VIOLATION')
    test=(path/REGRESSION).read_text()
    if 'noSourcesDesc' not in test or 'en-US' not in test or 'zh-CN' not in test:fail('ITERATION_REGRESSION_REQUIRED')
    return {'status':'PASSED','platform_verification':verification,'baseline':baseline,'scope':sorted(paths),'catalog_keys_unchanged':True,'locales':['en-US','zh-CN'],
            'changes':{k:{'before':before[k],'after':after[k]} for k in changed},
            'files':{n:hashlib.sha256((path/n).read_bytes()).hexdigest() for n in ALLOWED}}


def verify_catalog_delta(before,after):
    """Platform-owned invariant, using the immutable Git baseline, not model tests."""
    if type(before) is not dict or type(after) is not dict or set(before)!=set(after):fail('ITERATION_SCOPE_VIOLATION')
    if any(before[k]!=after[k] for k in before if k!='noSourcesDesc'):fail('ITERATION_SCOPE_VIOLATION')
    value=after.get('noSourcesDesc')
    if type(value) is not dict or set(value)!={'en-US','zh-CN'} or any(type(v) is not str or not 5<=len(v)<=500 for v in value.values()):fail('ITERATION_TRANSLATION_INVALID')
    if value==before['noSourcesDesc']:fail('ITERATION_NO_CHANGES')
    if any(value[k]==before['noSourcesDesc'][k] for k in ('en-US','zh-CN')):fail('ITERATION_BOTH_LOCALES_REQUIRED')
    return {'checker':'IMMUTABLE_BASELINE_BOTH_LOCALES_2','both_locales_changed':True,
            'non_target_values_unchanged':True,'semantic_review':'SEPARATE_REQUIRED'}


class TargetIn(Strict):
    path:str=Field(min_length=1,max_length=1500)

class TargetConfirm(Strict):
    preview_hash:str
    confirmation:bool

class IterationIn(Strict):
    body:str=Field(min_length=1,max_length=12000)
    output_locale:str
    request_id:str=Field(min_length=8,max_length=80)
    confirmation:bool

class IterationRevisionIn(IterationIn):
    expected_revision:int=Field(ge=1)

class StageIn(StartIn):
    pass

class CommitReviewIn(Strict):
    name:str=Field(min_length=1,max_length=100)
    email:str=Field(min_length=3,max_length=240)

class ExactConfirm(Strict):
    digest:str
    confirmation:bool
    ui_locale:str


def serialize(session):
    if session.get_bind().dialect.name=='sqlite': session.execute(text('BEGIN IMMEDIATE'))
    session.expire_all()


def install(app,settings,get_db,current_user,service):
    @app.post('/api/r2/projects/{project_id}/target/preview')
    def preview_target(project_id:int,payload:TargetIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); serialize(session); space=owned(session,project_id,user)
        if space.kind!='development':fail('DEVELOPMENT_PROJECT_REQUIRED')
        try:value=source_identity(payload.path,settings)
        except (OSError,ValueError):fail('DEVELOPMENT_PATH_UNAVAILABLE')
        saved=json.loads(space.target_json)
        target=isolated_target(settings,project_id)
        changed=bool(saved and any(saved.get(k)!=v for k,v in value.items()))
        if changed:
            if session.scalar(select(WorkItem.id).where(WorkItem.project_id==project_id)):fail('DEVELOPMENT_TARGET_IN_USE')
            target=target.parent/(str(project_id)+'-source-'+value['commit'][:16])
        value.update({'allowed_files':list(ALLOWED),'allowed_catalog_keys':['noSourcesDesc'],
            'controller_writes':False,'original_source_writes':False,'candidate_snapshot':str(target),
            'previous_snapshot_preserved':saved.get('snapshot') if changed else saved.get('previous_snapshot_preserved')})
        value['preview_hash']=digest(value)
        save_preference(session,'target_preview:'+str(project_id),value)
        return value

    @app.post('/api/r2/projects/{project_id}/target/confirm')
    def confirm_target(project_id:int,payload:TargetConfirm,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); serialize(session); space=owned(session,project_id,user)
        if space.kind!='development' or not payload.confirmation:fail('DEVELOPMENT_CONFIRMATION_REQUIRED')
        prior=preference(session,'target_preview:'+str(project_id))
        if not prior or payload.preview_hash!=prior['preview_hash']:fail('DEVELOPMENT_TARGET_CHANGED')
        current=source_identity(prior['path'],settings)
        if any(prior[k]!=v for k,v in current.items()):fail('DEVELOPMENT_TARGET_CHANGED')
        saved=json.loads(space.target_json)
        changed=bool(saved and any(saved.get(k)!=v for k,v in current.items()))
        if changed and session.scalar(select(WorkItem.id).where(WorkItem.project_id==project_id)):fail('DEVELOPMENT_TARGET_IN_USE')
        target=Path(prior['candidate_snapshot'])
        if target.parent!=isolated_target(settings,project_id).parent or target.is_symlink():fail('DEVELOPMENT_PATH_UNSAFE')
        from .managed_workspace import private_path
        private_path(target.parent)
        if target.exists():
            if not changed and saved.get('snapshot')==str(target) and git(target,'rev-parse','HEAD').strip()==prior['commit']:return saved
            fail('DEVELOPMENT_SNAPSHOT_EXISTS')
        # Local clone of the exact reviewed source; no hardlinks and no remote network.
        git(target.parent,'clone','--no-hardlinks','--no-local','--template=',prior['path'],str(target))
        git(target,'remote','remove','origin')
        if git(target,'rev-parse','HEAD').strip()!=prior['commit']:fail('DEVELOPMENT_TARGET_CHANGED')
        if saved:activity(session,project_id,'UNUSED_DEVELOPMENT_TARGET_REPLACED',{'previous':saved,'new_preview':prior,'old_snapshot_retained':True})
        space.target_json=encoded({**prior,'snapshot':str(target),'confirmed_at':now()})
        activity(session,project_id,'DEVELOPMENT_TARGET_CONFIRMED',json.loads(space.target_json))
        return json.loads(space.target_json)

    @app.post('/api/r2/projects/{project_id}/iterations',status_code=202)
    def create_iteration(project_id:int,payload:IterationIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); serialize(session); space=owned(session,project_id,user)
        key='iteration_create:'+str(project_id)+':'+payload.request_id
        binding=digest(payload.model_dump())
        prior=preference(session,key)
        if prior:
            if prior['binding']!=binding:fail('IDEMPOTENCY_CONFLICT')
            return execution_out(session.get(WorkExecution,prior['execution_id']))
        from .desktop import build_identity
        if build_identity().get('self_iteration_test_artifact'):fail('CHILD_ARTIFACT_ITERATION_DISABLED')
        if space.kind!='development' or not json.loads(space.target_json).get('snapshot'):fail('DEVELOPMENT_TARGET_REQUIRED')
        if not payload.confirmation or payload.output_locale not in ('en-US','zh-CN'):fail('START_CONFIRMATION_REQUIRED')
        if session.scalar(select(WorkItem).where(WorkItem.project_id==project_id,WorkItem.kind=='iteration',WorkItem.state.not_in(['REVIEW_FAILED','CANCELLED','INTERRUPTED','FAILED']))):fail('ITERATION_ALREADY_ACTIVE')
        w=WorkItem(id=identity('iteration'),project_id=project_id,kind='iteration',title=payload.body[:70],body=payload.body,
            output_locale=payload.output_locale,sources_json='[]',created_at=now())
        session.add(w);session.flush()
        activity(session,project_id,'ITERATION_REQUESTED',{'body':w.body},'user',w.id)
        row=admit_stage(session,settings,w,space,'planner',payload.request_id)
        save_preference(session,key,{'binding':binding,'execution_id':row.id})
        session.commit();service.start(row.id)
        return execution_out(row)

    @app.post('/api/r2/iterations/{work_id}/{stage}',status_code=202)
    def stage_action(work_id:str,stage:str,payload:StageIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); serialize(session); w,space=work_owned(session,work_id,user)
        if w.kind!='iteration' or stage not in ('execute','review'):fail('ITERATION_ACTION_INVALID',422)
        if not payload.confirmation or payload.plan_hash!=w.plan_hash:fail('APPROVAL_CHANGED')
        prior=session.scalar(select(WorkExecution).where(WorkExecution.work_id==w.id,WorkExecution.idempotency_key==payload.request_id))
        if prior:
            if prior.phase!=('executor' if stage=='execute' else 'reviewer') or prior.plan_hash!=payload.plan_hash:fail('IDEMPOTENCY_CONFLICT')
            return execution_out(prior)
        required='APPROVED' if stage=='execute' else 'BUILT'
        if w.state!=required:fail('ITERATION_STATE_CHANGED')
        if stage=='execute' and json.loads(w.approval_json).get('plan_hash')!=w.plan_hash:fail('APPROVAL_REQUIRED')
        if stage=='review':executed_regression(session,w,Path(json.loads(space.target_json)['snapshot']),json.loads(space.target_json)['commit'])
        row=admit_stage(session,settings,w,space,'executor' if stage=='execute' else 'reviewer',payload.request_id)
        session.commit();service.start(row.id)
        return execution_out(row)

    @app.post('/api/r2/iterations/{work_id}/revision/plan',status_code=202)
    def revise_iteration(work_id:str,payload:IterationRevisionIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request);serialize(session);w,space=work_owned(session,work_id,user)
        key='iteration_revision:'+w.id+':'+payload.request_id;binding=digest(payload.model_dump());prior=preference(session,key)
        if prior:
            if prior['binding']!=binding:fail('IDEMPOTENCY_CONFLICT')
            return execution_out(session.get(WorkExecution,prior['execution_id']))
        if w.kind!='iteration' or w.revision!=payload.expected_revision or w.state not in ('PLANNED','APPROVED','REPLAN_REQUIRED','FAILED','CANCELLED','INTERRUPTED','REVIEW_FAILED'):fail('ITERATION_STATE_CHANGED')
        if not payload.confirmation or payload.output_locale not in ('en-US','zh-CN'):fail('START_CONFIRMATION_REQUIRED')
        from .desktop import build_identity
        if build_identity().get('self_iteration_test_artifact'):fail('CHILD_ARTIFACT_ITERATION_DISABLED')
        target=json.loads(space.target_json);original=source_identity(target['path'],settings)
        if original['commit']!=target['commit']:fail('DEVELOPMENT_TARGET_CHANGED')
        # Keep all prior files/diffs, including a failed partial implementation.
        # A new revision gets its own clone of the originally authorized baseline.
        destination=isolated_target(settings,w.project_id).parent/(w.id+'-revision-'+str(w.revision+1)+'-'+uuid.uuid4().hex[:8])
        git(destination.parent,'clone','--no-hardlinks','--no-local','--template=',target['path'],str(destination))
        git(destination,'remote','remove','origin')
        if git(destination,'rev-parse','HEAD').strip()!=target['commit']:fail('DEVELOPMENT_TARGET_CHANGED')
        activity(session,w.project_id,'ITERATION_REVISION_ARCHIVED',{'work':work_out(w),'target':target},'user',w.id)
        target['snapshot']=str(destination);space.target_json=encoded(target)
        try:handoff=json.loads(payload.body)
        except (ValueError,TypeError):handoff=None
        title=handoff.get('instruction') if isinstance(handoff,dict) and handoff.get('chat_id') else None
        w.body=payload.body;w.title=(title if isinstance(title,str) and title.strip() else payload.body)[:160];w.output_locale=payload.output_locale;w.revision+=1
        w.plan_json='{}';w.plan_hash='';w.approval_json='{}'
        row=admit_stage(session,settings,w,space,'planner',payload.request_id)
        save_preference(session,key,{'binding':binding,'execution_id':row.id})
        session.commit();service.start(row.id)
        return execution_out(row)

    @app.post('/api/r2/iterations/{work_id}/candidate/review')
    def review_candidate(work_id:str,payload:CommitReviewIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); serialize(session); w,space=work_owned(session,work_id,user)
        if w.kind!='iteration' or w.state!='REVIEWED':fail('INDEPENDENT_REVIEW_REQUIRED')
        if any(c in payload.name+payload.email for c in '\n\r\0') or '@' not in payload.email:fail('COMMIT_IDENTITY_INVALID',422)
        review=session.scalar(select(WorkExecution).where(WorkExecution.work_id==w.id,WorkExecution.phase=='reviewer',WorkExecution.state=='COMPLETED').order_by(WorkExecution.started_at.desc()))
        if not review:fail('INDEPENDENT_REVIEW_REQUIRED')
        from .iteration_candidate import candidate_preview
        target=json.loads(space.target_json)
        preview=candidate_preview(Path(target['snapshot']),target['commit'],json.loads(review.evidence_json))
        preview.update(work_id=w.id,plan_hash=w.plan_hash,author_name=payload.name,author_email=payload.email,
                       subject='Improve bilingual empty-project guidance',review_execution=review.id)
        preview['digest']=digest(preview)
        save_preference(session,'candidate_preview:'+w.id,preview)
        save_preference(session,'candidate_approval:'+w.id,None)
        activity(session,w.project_id,'LOCAL_COMMIT_REVIEWED',preview,'user',w.id)
        return preview

    @app.post('/api/r2/iterations/{work_id}/candidate/approve')
    def approve_candidate(work_id:str,payload:ExactConfirm,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); serialize(session); w,space=work_owned(session,work_id,user)
        if json.loads(w.plan_json).get('recovery_epoch','')!=recovery_epoch(settings):fail('RECOVERY_REPLAN_REQUIRED')
        preview=preference(session,'candidate_preview:'+w.id)
        if w.state!='REVIEWED' or not preview or payload.digest!=preview['digest'] or not payload.confirmation or payload.ui_locale not in ('en-US','zh-CN'):fail('APPROVAL_CHANGED')
        approval={'digest':payload.digest,'actor_id':user.id,'ui_locale':payload.ui_locale,'at':now(),'type':'OWNER_APPROVED','scope':'LOCAL_CANDIDATE_COMMIT_ONLY'}
        save_preference(session,'candidate_approval:'+w.id,approval)
        activity(session,w.project_id,'LOCAL_COMMIT_APPROVED',approval,'user',w.id)
        return approval

    @app.post('/api/r2/iterations/{work_id}/candidate/commit')
    def commit_candidate(work_id:str,payload:ExactConfirm,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); serialize(session); w,space=work_owned(session,work_id,user)
        if json.loads(w.plan_json).get('recovery_epoch','')!=recovery_epoch(settings):fail('RECOVERY_REPLAN_REQUIRED')
        preview=preference(session,'candidate_preview:'+w.id);approval=preference(session,'candidate_approval:'+w.id)
        if w.state!='REVIEWED' or not preview or not approval or payload.digest!=preview['digest'] or approval['digest']!=payload.digest or not payload.confirmation:fail('APPROVAL_REQUIRED')
        from .iteration_candidate import commit_candidate as perform_commit
        root=Path(json.loads(space.target_json)['snapshot'])
        w.state='COMMITTING';session.commit()  # consumed before irreversible local action
        try:
            commit=perform_commit(root,preview,name=preview['author_name'],email=preview['author_email'])
        except Exception:
            w.state='COMMIT_RECONCILIATION_REQUIRED';session.commit();raise
        w.state='COMMITTED';save_preference(session,'candidate_commit:'+w.id,commit)
        activity(session,w.project_id,'LOCAL_CANDIDATE_COMMIT_CONFIRMED',{'commit':commit,'parent':preview['baseline'],'digest':payload.digest},'user',w.id)
        return {'commit':commit,'state':w.state,'push_performed':False}

    @app.post('/api/r2/iterations/{work_id}/candidate/build',status_code=202)
    def build_candidate(work_id:str,payload:ExactConfirm,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); serialize(session); w,space=work_owned(session,work_id,user)
        if json.loads(w.plan_json).get('recovery_epoch','')!=recovery_epoch(settings):fail('RECOVERY_REPLAN_REQUIRED')
        preview=preference(session,'candidate_preview:'+w.id);commit=preference(session,'candidate_commit:'+w.id)
        if w.state!='COMMITTED' or not preview or not commit or payload.digest!=preview['digest'] or not payload.confirmation:fail('APPROVAL_CHANGED')
        target=json.loads(space.target_json);destination=isolated_target(settings,w.project_id).parent/(w.id+'-candidate')
        row=WorkExecution(id=identity('build'),work_id=w.id,revision=w.revision,phase='candidate',idempotency_key=payload.digest,
            plan_hash=w.plan_hash,state='QUEUED',input_json=encoded({'root':target['snapshot'],'preview':preview,'commit':commit,'destination':str(destination)}),started_at=now())
        session.add(row);w.state='RUNNING';session.commit();service.start(row.id)
        return execution_out(row)

    @app.post('/api/r2/iterations/{work_id}/update/prepare')
    async def prepare_update(work_id:str,request:Request):
        mutation(request)
        # Owner authentication, request exclusion and worker settlement are
        # enforced by the existing maintenance coordinator. Do not retain a
        # dependency Session (or request read lease) through its exclusive lock.
        def prepare(owner_id):
            from types import SimpleNamespace
            with app.state.session_factory() as session:
                w,space=work_owned(session,work_id,SimpleNamespace(id=owner_id))
                if w.state!='CANDIDATE_READY':fail('CANDIDATE_NOT_READY')
                if json.loads(w.plan_json).get('recovery_epoch','')!=recovery_epoch(settings):fail('RECOVERY_REPLAN_REQUIRED')
                row=session.scalar(select(WorkExecution).where(WorkExecution.work_id==w.id,WorkExecution.phase=='candidate',WorkExecution.state=='COMPLETED',WorkExecution.revision==w.revision,WorkExecution.plan_hash==w.plan_hash))
                if row is None:fail('CANDIDATE_NOT_READY')
                receipt=json.loads(row.evidence_json)
                if hashlib.sha256(Path(receipt['artifact']).read_bytes()).hexdigest()!=receipt['sha256']:fail('CANDIDATE_INPUT_CHANGED')
                project_id=w.project_id
            # Closing a Session returns its connection to the pool. Dispose
            # that pool as well, before acquiring the cross-process lease.
            app.state.engine.dispose()
            backup=app.state.maintenance.create_backup()
            value={'candidate':receipt,'backup':backup,'method':'OWNER_GUI_DMG','prepared_at':now(),
                   'rollback':'APP_ONLY_KEEP_DATA','automatic_in_app_update':False,'installed':False}
            value['digest']=digest(value)
            with app.state.session_factory() as session:
                save_preference(session,'update_preview:'+work_id,value)
                activity(session,project_id,'UPDATE_PREPARED',value,'system',work_id)
                session.commit()
            return value
        return await app.state.maintenance_mutate(request,prepare)

    @app.post('/api/r2/iterations/{work_id}/update/confirm')
    def confirm_update(work_id:str,payload:ExactConfirm,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); serialize(session); w,space=work_owned(session,work_id,user)
        if json.loads(w.plan_json).get('recovery_epoch','')!=recovery_epoch(settings):fail('RECOVERY_REPLAN_REQUIRED')
        value=preference(session,'update_preview:'+w.id)
        if not value or not payload.confirmation or value['digest']!=payload.digest or w.state!='CANDIDATE_READY':fail('APPROVAL_CHANGED')
        artifact=Path(value['candidate']['artifact'])
        if service.jobs or hashlib.sha256(artifact.read_bytes()).hexdigest()!=value['candidate']['sha256']:fail('CANDIDATE_INPUT_CHANGED')
        save_preference(session,'pending_update',{'work_id':w.id,'project_id':w.project_id,'candidate':value['candidate'],'method':'OWNER_GUI_DMG','confirmed_at':now()})
        activity(session,w.project_id,'OWNER_GUI_INSTALL_REQUESTED',{'candidate_sha256':value['candidate']['sha256'],'method':'OWNER_GUI_DMG','installed':False},'user',w.id)
        session.commit()
        subprocess.run(['/usr/bin/open',str(artifact)],check=True,timeout=10)
        return {'status':'AWAITING_OWNER_GUI_INSTALL','installed':False,'method':'OWNER_GUI_DMG'}

    @app.get('/api/r2/update-status')
    def update_status(session=Depends(get_db),user=Depends(current_user)):
        from .desktop import build_identity
        pending=preference(session,'pending_update')
        actual=build_identity()
        if pending:
            owned(session,pending['project_id'],user)
        matched=bool(pending and actual.get('source_commit')==pending['candidate']['source_commit'] and actual.get('build_version')==pending['candidate']['build'])
        return {'pending':pending,'running':actual,'installed_identity_matches':matched,'owner_accepted':False,'health':'healthy'}

    @app.post('/api/r2/update-status/record')
    def record_update_status(request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); serialize(session)
        value=update_status(session,user)
        pending=value['pending']
        if pending and value['installed_identity_matches']:
            key='installed_update:'+pending['candidate']['sha256']
            receipt=preference(session,key)
            if not receipt:
                receipt={**value,'verified_at':now(),'owner_accepted':False}
                save_preference(session,key,receipt)
                activity(session,pending['project_id'],'CANDIDATE_INSTALLED_IDENTITY_VERIFIED',receipt,'system',pending['work_id'])
            value['installed_receipt']=receipt
        return value


def admit_stage(session,settings,w,space,phase,request_id):
    team=json.loads(space.team_json);target=json.loads(space.target_json)
    if not team:fail('TEAM_REQUIRED')
    if not any(c['id']==team['tool_id'] for c in tool_recovery.candidates(settings)):fail('EXECUTABLE_MISSING_OR_CHANGED')
    budget_key=provider_budget_key(session,space.owner_id)
    budget=preference(session,budget_key,{'limit':0,'used':0})
    # Owner removed the application call cap; preserve the historical counter only.
    from .iteration_contract import identity as contract_identity
    if phase!='planner' and json.loads(w.plan_json).get('response_contract')!=contract_identity():fail('ITERATION_CONTRACT_CHANGED')
    if phase!='planner' and json.loads(w.plan_json).get('team_hash')!=team['configuration_hash']:fail('TEAM_CHANGED')
    if phase!='planner' and json.loads(w.plan_json).get('recovery_epoch','')!=recovery_epoch(settings):fail('RECOVERY_REPLAN_REQUIRED')
    root=Path(target['snapshot'])
    if not root.is_dir() or root.is_symlink() or git(root,'rev-parse','HEAD').strip()!=target['commit']:fail('DEVELOPMENT_TARGET_CHANGED')
    if phase in ('planner','executor') and git(root,'status','--porcelain').strip():fail('DEVELOPMENT_SOURCE_DIRTY')
    row=WorkExecution(id=identity('execution'),work_id=w.id,revision=w.revision,phase=phase,idempotency_key=request_id,
        plan_hash=w.plan_hash,state='QUEUED',input_json=encoded({'team':team,'target':target,'body':w.body,'output_locale':w.output_locale,'plan':json.loads(w.plan_json)}),started_at=now())
    session.add(row);w.state='RUNNING';budget['used']+=1;save_preference(session,budget_key,budget)
    activity(session,w.project_id,'ITERATION_'+phase.upper()+'_STARTED',{'execution_id':row.id},'user',w.id)
    session.flush();return row


def execute_stage(service,eid,cancel,spawned):
    with service.factory() as session:
        row=session.get(WorkExecution,eid);phase=row.phase;inputs=json.loads(row.input_json);work=session.get(WorkItem,row.work_id)
        work_id=work.id;project_id=work.project_id;revision=work.revision
    from .iteration_contract import schema_path,identity as contract_identity,parse
    root=Path(inputs['target']['snapshot']);team=inputs['team'];target=inputs['target'];body=inputs['body']
    base=('You are part of an explicitly controlled TWOS product iteration. No external tools, network, credentials, trading, clinical actions or approval changes. '
          'The running controller and original source cannot be modified. Only '+', '.join(ALLOWED)+' may change in the isolated target. '
          'Only catalog key noSourcesDesc may change; preserve every other catalog entry and add a unittest regression using only json, pathlib, unittest. '
          'Verification responsibilities are fixed: the generated unittest must assert the exact new bilingual pair and may also check semantic clauses. '
          'The protected controller, not the generated test, compares ALL non-target entries to the immutable Git baseline and runs the test plus negative controls for each old locale. '
          'Do not promise a test-embedded baseline catalog or semantic-only tests without exact-pair assertions. '
          'A separate Start authorizes the controller to apply the permitted response and run these checks; the model itself cannot run commands. '
          'No commit, push, install, commands or additional agents. Write prose in '+inputs['output_locale']+'.\nRequest: '+body+'\n')
    if phase=='planner':
        prompt=base+'Produce a scoped plan: the bilingual empty-source guidance improvement, exact allowed files, tests, risks and exclusions. This request does not authorize implementation.\nCurrent entry: '+encoded(json.loads((root/CATALOG).read_text())['noSourcesDesc'])
    elif phase=='executor':
        current=json.loads((root/CATALOG).read_text())['noSourcesDesc']
        prompt=(base+'This is the separately approved implementation phase. Planning-only disclaimers in the historical plan describe its earlier phase. '
                'EXECUTION_PATCH_RESPONSE: return one JSON object only, with exactly these keys: '
                'schema ("twos.iteration.patch.v1"), baseline (the exact commit below), catalog_sha256 (the exact hash below), '
                'replacement (object with improved en-US and zh-CN strings for noSourcesDesc only), '
                'regression (complete Python unittest source as a JSON string), summary (brief explanation). '
                'Do not call tools or write files. The protected controller applies this structured response only to the two allowed files, '
                'then runs the regression in a read-only no-network sandbox before allowing independent review. '
                'Use only json, pathlib, unittest; define unittest.TestCase with meaningful assertions about both new language strings. '
                'Encode regression as a JSON string exactly once: after JSON decoding, the Python source must contain actual newlines, not literal backslash-n separators. '
                'Use Path(__file__).resolve().parents[1] as the repository root. Do not run unittest.main at import time. '
                'Both language values must differ from their exact old values and fulfill the approved plan. Preserve its exact bilingual wording when specified; do not substitute a different workflow or add an unrequested import prerequisite. '
                'Your test must assert the exact new pair and fail against the provided old pair; do not compare data to itself. '
                'The protected platform separately compares ALL non-target entries to the immutable Git baseline. '
                'The UI reads this entry as catalog[noSourcesDesc][locale] via textContent; no HTML is allowed. '
                'Do not include markdown fences or any extra fields.\nBASELINE: '+target['commit']+
                '\nCATALOG SHA256: '+hashlib.sha256((root/CATALOG).read_bytes()).hexdigest()+
                '\nCURRENT CATALOG ENTRY:\n'+json.dumps({'noSourcesDesc':current},ensure_ascii=False,indent=2)+
                '\nAPPROVED PLAN:\n'+encoded(inputs['plan']))
    else:
        checks=check_changes(root,target['commit'])
        with service.factory() as session:
            test_binding=executed_regression(session,session.get(WorkItem,work_id),root,target['commit'])
        diff=git(root,'diff',target['commit'],'--',CATALOG)+'\nNEW TEST:\n'+(root/REGRESSION).read_text()
        prompt=base+'Review this actual diff independently, read-only. Return JSON only: {"verdict":"PASS" or "FAIL","reason":"..."}. Never approve as a human.\n'+diff+'\nApproved plan:\n'+encoded(inputs['plan'])+'\nController checks:\n'+encoded(checks)+'\nExecuted regression binding:\n'+encoded(test_binding)
    contract=contract_identity()
    prompt+='\nRESPONSE CONTRACT IDENTITY:\n'+encoded(contract)
    options={'write':False}
    if phase in ('executor','reviewer'):
        options['output_schema']=schema_path(phase)
        prompt+='\nEXACT JSON SCHEMA SUPPLIED TO CLI:\n'+schema_path(phase).read_text()
    output,evidence=service.invoke(eid,phase,inputs,team['executable'],team[phase],prompt,root,cancel,spawned,**options)
    evidence.update({'input_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'output_sha256':hashlib.sha256(output.encode()).hexdigest(),
                     'response_contract':contract,'work_id':work_id,'revision':revision,'plan_hash':row.plan_hash,'phase':phase,'development_baseline':target['commit'],'controller_unchanged':True})
    # Keep the already secret-screened model response when subsequent protected
    # validation rejects it. A response is evidence, not an accepted candidate.
    with service.factory() as session:
        row=session.get(WorkExecution,eid)
        row.output=output;row.evidence_json=encoded({**evidence,'validation':'PENDING_CONTROLLER_CHECKS'})
        activity(session,project_id,'ITERATION_MODEL_RESPONSE',{'execution_id':eid,'phase':phase,
            'output':output,'evidence':evidence,'validation':'PENDING_CONTROLLER_CHECKS'},
            'independent_review' if phase=='reviewer' else 'planning_reply' if phase=='planner' else 'execution_tool',work_id)
        session.commit()
    with service.factory() as session:
        w=session.get(WorkItem,work_id);row=session.get(WorkExecution,eid)
        if phase=='planner':
            plan={'project_id':project_id,'work_id':work_id,'revision':revision,'body':body,'output_locale':inputs['output_locale'],
                'plan_text':output,'team_hash':team['configuration_hash'],'team_mode':team['mode'],
                'models':{r:team[r] for r in ('planner','executor','reviewer')},'target':target,
                'allowed_files':list(ALLOWED),'allowed_catalog_keys':['noSourcesDesc'],'cli_invocations_remaining':2,'response_contract':contract,
                'execution_channel':'STRUCTURED_PATCH_V1','commit_approval':'SEPARATE_REQUIRED','install_approval':'SEPARATE_REQUIRED','public_push':False,'recovery_epoch':recovery_epoch(service.settings)}
            w.plan_json=encoded(plan);w.plan_hash=digest(plan);w.state='PLANNED';w.approval_json='{}'
        elif phase=='executor':
            evidence['patch_application']=apply_structured_patch(root,target['commit'],output)
            evidence['schema_validation']='PASSED'
            evidence['candidate_staging']='APPLIED'
            evidence['deterministic_checks']=check_changes(root,target['commit'])
            evidence['diff']=git(root,'diff',target['commit'],'--',CATALOG)
            evidence['new_test']=(root/REGRESSION).read_text()
            row.evidence_json=encoded({**evidence,'validation':'PENDING_REGRESSION'})
            session.commit()
            from .iteration_candidate import run_regression,validate_generated_regression,bundle_path
            evidence['regression']=run_regression(root,bundle_path())
            evidence['regression_sensitivity']=validate_generated_regression(root,target['commit'],bundle_path())
            w.state='BUILT'
        else:
            try:review=parse(output,'reviewer')
            except ValueError:fail('REVIEW_FORMAT_INVALID')
            if not review['reason'].strip() or len(review['reason'])>12000:fail('REVIEW_FORMAT_INVALID')
            # Extraction only proves the transport channel. Record the actual
            # strict controller validation independently of the review verdict.
            # Persist it before later scope checks, which can fail separately.
            evidence['schema_validation']='PASSED'
            evidence['independent_review']=review
            row.evidence_json=encoded({**evidence,'validation':'PENDING_CONTROLLER_CHECKS'})
            session.commit()
            evidence['review_independence']='SEPARATE_SESSION_SAME_MODEL' if team['reviewer']==team['executor'] else 'SEPARATE_SESSION_DIFFERENT_REQUESTED_MODEL'
            evidence['deterministic_checks']=check_changes(root,target['commit'])
            evidence['executed_regression_binding']=test_binding
            w.state='REVIEWED' if review['verdict']=='PASS' else 'REVIEW_FAILED'
        evidence['validation']='PASSED'
        row.output=output;row.evidence_json=encoded(evidence);row.state='COMPLETED';row.finished_at=now()
        activity(session,project_id,'ITERATION_'+phase.upper()+'_RESULT',{'execution_id':eid,'output':output,'evidence':evidence},'independent_review' if phase=='reviewer' else 'planning_reply' if phase=='planner' else 'execution_tool',work_id)
        session.commit()
