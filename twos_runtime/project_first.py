"""Project-first product API: explicit actions, immutable inputs, local results.

This extension does not grant execution through the legacy workspace gates.
Ordinary document work writes only its app-managed result records, never sources.
"""
from __future__ import annotations
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import uuid

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text

from .models import Project, Task, Installation, AuthorizedWorkspace, utc_now
from .project_first_models import (ProjectSpace, ProjectSource, ImportPreview, WorkItem,
                                 WorkExecution, ProjectActivity, ProductPreference)
from . import project_sources, tool_recovery

LOCALES = ('en-US', 'zh-CN')
KINDS = ('blank','ldd','dashu','development')
EXTENSION_VERSION = 'project-first.1'


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def identity(prefix):
    return prefix + '_' + uuid.uuid4().hex


def recovery_epoch(settings):
    if not settings.data_root:
        return ''
    from .maintenance import Maintenance
    return Maintenance(settings).authority().get('epoch','')


class ProjectError(HTTPException):
    """Stable public codes; never expose provider output or an exception trace."""


def fail(code, status=409):
    raise ProjectError(status, detail={'code':code})


def mutation(request):
    origin = request.headers.get('origin')
    if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != str(request.base_url).rstrip('/')):
        fail('ORIGIN_MISMATCH',403)
    if request.headers.get('content-type','').split(';')[0] != 'application/json':
        fail('JSON_REQUIRED',415)


def owned(session, project_id, user):
    row = session.get(ProjectSpace, project_id)
    if row is None or row.owner_id != user.id:
        fail('PROJECT_NOT_FOUND',404)
    return row


def work_owned(session, work_id, user):
    row = session.get(WorkItem,work_id)
    if row is None:
        fail('TASK_NOT_FOUND',404)
    return row, owned(session,row.project_id,user)


def activity(session, project_id, event, payload, source='user', work_id=None):
    session.add(ProjectActivity(project_id=project_id,work_id=work_id,event=event,
                  source_type=source,content_json=encoded(payload),created_at=now()))


def preference(session,key,default=None):
    row=session.get(ProductPreference,key)
    return json.loads(row.value_json) if row else default


def save_preference(session,key,value):
    row=session.get(ProductPreference,key)
    if row:
        row.value_json=encoded(value)
    else:
        session.add(ProductPreference(key=key,value_json=encoded(value)))


def provider_budget_key(session, owner_id):
    """Keep accepted legacy budgets; email-only accounts cannot edit that row."""
    from .models import User
    user = session.get(User, owner_id)
    return 'provider_budget:'+str(owner_id) if user and user.username.startswith('email_user_') else 'provider_budget'


def work_out(row):
    return {'id':row.id,'project_id':row.project_id,'kind':row.kind,'title':row.title,
            'body':row.body,'output_locale':row.output_locale,'sources':json.loads(row.sources_json),
            'revision':row.revision,'state':row.state,'plan':json.loads(row.plan_json),
            'plan_hash':row.plan_hash,'approval':json.loads(row.approval_json),'created_at':row.created_at}


def execution_out(row):
    return {'id':row.id,'work_id':row.work_id,'revision':row.revision,'phase':row.phase,
            'state':row.state,'plan_hash':row.plan_hash,'output':row.output,'error_code':row.error_code,
            'evidence':json.loads(row.evidence_json),'started_at':row.started_at,'finished_at':row.finished_at}


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')

class LocaleIn(Strict):
    locale: str

class ProjectIn(Strict):
    name: str=Field(min_length=1,max_length=160)
    goal: str=Field(max_length=20000)
    kind: str
    confirmation: bool
    request_id: str=Field(min_length=8,max_length=80)

class ImportIn(Strict):
    filename: str=Field(min_length=1,max_length=512)
    data_base64: str=Field(max_length=45_000_000)

class ImportConfirm(Strict):
    sha256: str
    names: list[str]=Field(max_length=1500)
    confirmation: bool

class TeamIn(Strict):
    tool_id: str
    planner: str=Field(max_length=100)
    executor: str=Field(max_length=100)
    reviewer: str=Field(max_length=100)
    request_limit: int | None=Field(default=None,ge=0)
    existing_plan_only: bool
    human_gates: list[str]=Field(max_length=10)

class WorkIn(Strict):
    title: str=Field(max_length=200)
    body: str=Field(min_length=1,max_length=20000)
    output_locale: str
    source_ids: list[str]=Field(max_length=60)

class WorkReviseIn(WorkIn):
    expected_revision: int = Field(ge=1)
    request_id: str = Field(min_length=8,max_length=80)

class ProjectEditIn(Strict):
    name: str = Field(min_length=1,max_length=160)
    goal: str = Field(max_length=20000)
    expected_digest: str

class ApprovalIn(Strict):
    plan_hash: str
    ui_locale: str
    confirmation: bool
    single_model_disclosed: bool

class StartIn(Strict):
    plan_hash: str
    request_id: str=Field(min_length=8,max_length=80)
    confirmation: bool


def install(app,settings,get_db,current_user,factory):
    @app.exception_handler(ProjectError)
    async def project_error(request,exc):
        return JSONResponse({'error':{'code':exc.detail['code']}},status_code=exc.status_code)

    from .project_execution import ExecutionService
    service=ExecutionService(factory,settings)
    app.state.project_execution=service

    @app.get('/project-manager',response_class=HTMLResponse)
    def project_ui():
        root=settings.static_cockpit_dir/'project_first'
        page=(root/'index.html').read_text()
        for asset in ('app.js','styles.css','catalog.json'):
            page=page.replace(asset+'?hash=BUILD',asset+'?sha256='+hashlib.sha256((root/asset).read_bytes()).hexdigest())
        return HTMLResponse(page,headers={'Cache-Control':'no-store'})

    @app.get('/projects')
    def workbench_entry():
        from fastapi.responses import RedirectResponse
        return RedirectResponse('/workbench', status_code=307)

    @app.get('/api/r2/preferences')
    def get_preferences(session=Depends(get_db)):
        locale=preference(session,'ui_locale','en-US')
        if settings.ui_preference_path and settings.ui_preference_path.is_file():
            try:
                selected=json.loads(settings.ui_preference_path.read_text()).get('locale')
                if selected in LOCALES: locale=selected
            except (OSError,ValueError): pass
        return {'locale':locale,'extension_version':EXTENSION_VERSION}

    @app.post('/api/r2/preferences')
    def set_preferences(payload:LocaleIn,request:Request,session=Depends(get_db)):
        mutation(request)
        if payload.locale not in LOCALES: fail('LOCALE_INVALID',422)
        save_preference(session,'ui_locale',payload.locale)
        # Also used by the native launcher; only a fixed enum, no identity data.
        if settings.ui_preference_path:
            from scripts.twos_bootstrap import atomic_private_json
            atomic_private_json(settings.ui_preference_path,{'locale':payload.locale})
        return {'locale':payload.locale,'business_records_changed':False,'provider_calls':0}

    @app.get('/api/r2/projects')
    def list_projects(session=Depends(get_db),user=Depends(current_user)):
        rows=session.scalars(select(ProjectSpace).where(ProjectSpace.owner_id==user.id)).all()
        result=[]
        for row in rows:
            result.append({'id':row.project_id,'name':session.get(Project,row.project_id).name,'kind':row.kind,
                'goal':row.goal,'legacy':False})
        primary=session.scalar(select(Installation).where(Installation.owner_user_id==user.id))
        legacy_ids=set(session.scalars(select(Task.project_id).where(Task.owner_user_id==user.id)).all())
        if primary:
            bound=session.scalar(select(AuthorizedWorkspace).where(AuthorizedWorkspace.installation_id==primary.id))
            if bound: legacy_ids.add(bound.project_id)
        for pid in sorted(legacy_ids-{r.project_id for r in rows}):
            project=session.get(Project,pid)
            if project: result.append({'id':pid,'name':project.name,'kind':'legacy','goal':'','legacy':True})
        return result

    @app.post('/api/r2/projects',status_code=201)
    def create_project(payload:ProjectIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request)
        if not payload.confirmation or payload.kind not in KINDS or not payload.name.strip(): fail('PROJECT_INPUT_INVALID',422)
        key='project_create:'+str(user.id)+':'+payload.request_id
        binding=digest(payload.model_dump())
        if session.get_bind().dialect.name=='sqlite': session.execute(text('BEGIN IMMEDIATE'))
        old=preference(session,key)
        if old:
            if old['binding']!=binding: fail('REQUEST_REUSED')
            return {'project_id':old['project_id']}
        installation=session.scalar(select(Installation)) if settings.fresh_install else None
        if installation and installation.owner_user_id!=user.id: fail('OWNER_REQUIRED',403)
        if installation and installation.first_run_state=='workspace_pending':
            from .managed_workspace import create_managed_workspace
            from .first_run import review_optional_tools,finish_first_run,sync_installation_configuration
            workspace=create_managed_workspace(session,settings,user)
            project=session.get(Project,workspace.project_id)
            project.name=payload.name.strip()
            object.__setattr__(settings,'source_repo',Path(workspace.canonical_path))
            review_optional_tools(session,settings,owner=user,decision='skip')
            finish_first_run(session,settings,owner=user)
            sync_installation_configuration(settings,installation)
        else:
            if installation and installation.first_run_state!='ready': fail('SETUP_REQUIRED')
            project=Project(key=identity('project'),name=payload.name.strip())
            session.add(project); session.flush()
        row=ProjectSpace(project_id=project.id,owner_id=user.id,kind=payload.kind,goal=payload.goal,created_at=now())
        session.add(row); session.flush()
        save_preference(session,'extension_version',EXTENSION_VERSION)
        save_preference(session,key,{'binding':binding,'project_id':project.id})
        activity(session,project.id,'PROJECT_CREATED',{'kind':payload.kind,'internal_storage_authorized':True})
        return {'project_id':project.id}

    @app.get('/api/r2/projects/{project_id}')
    def project_detail(project_id:int,session=Depends(get_db),user=Depends(current_user)):
        space=owned(session,project_id,user)
        sources=session.scalars(select(ProjectSource).where(ProjectSource.project_id==project_id)).all()
        works=session.scalars(select(WorkItem).where(WorkItem.project_id==project_id).order_by(WorkItem.created_at)).all()
        executions=session.scalars(select(WorkExecution).join(WorkItem).where(WorkItem.project_id==project_id).order_by(WorkExecution.started_at)).all()
        events=session.scalars(select(ProjectActivity).where(ProjectActivity.project_id==project_id).order_by(ProjectActivity.id)).all()
        team=json.loads(space.team_json)
        current=tool_recovery.candidates(settings)
        tool=next((t for t in current if t['id']==team.get('tool_id')),None)
        from .workbench_models import Delivery
        deliveries=session.scalars(select(Delivery).where(Delivery.project_id==project_id,Delivery.owner_id==user.id).order_by(Delivery.created_at)).all()
        return {'id':project_id,'name':session.get(Project,project_id).name,'kind':space.kind,'goal':space.goal,
            'context_digest':digest({'name':session.get(Project,project_id).name,'goal':space.goal}),
            'sources':[{'id':s.id,'name':s.name,'sha256':s.sha256,'language':s.language,'receipt_id':s.receipt_id,'created_at':s.created_at} for s in sources],
            'integrated':{'team':preference(session,'wb:team:'+str(project_id),{}),'workspace':preference(session,'wb:workspace:'+str(project_id),{})},
            'deliveries':[{'id':d.id,'chat_id':d.chat_id,'state':d.state,'title':json.loads(d.specification_json)['title'],
                'objective':json.loads(d.specification_json)['objective'],'output':d.output,'review':d.review,
                'files':preference(session,'wb:artifacts:'+d.id,{}).get('files',[])} for d in deliveries],
            'team':team,'target':json.loads(space.target_json),'configuration_saved':bool(team),
            'tool_state':'SELECTED_NOT_PROBED' if tool else 'EXECUTABLE_MISSING_OR_CHANGED' if team else 'NOT_CONFIGURED',
            'works':[work_out(w) for w in works],'executions':[execution_out(e) for e in executions],
            'activity':[{'id':e.id,'work_id':e.work_id,'source_type':e.source_type,'event':e.event,'content':json.loads(e.content_json),'created_at':e.created_at} for e in events],
            'candidate_state':{w.id:{'preview':preference(session,'candidate_preview:'+w.id),'approval':preference(session,'candidate_approval:'+w.id),'commit':preference(session,'candidate_commit:'+w.id)} for w in works if w.kind=='iteration'},
            'request_budget':{**preference(session,provider_budget_key(session,user.id),{'used':0}),'limit':None},
            'boundaries':{'order_authority':'NONE','clinical_authority':'NONE','automatic_approval':False}}

    @app.post('/api/r2/projects/{project_id}/imports/preview')
    def preview_import(project_id:int,payload:ImportIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); owned(session,project_id,user)
        try:
            data=base64.b64decode(payload.data_base64,validate=True)
            result=project_sources.preview(payload.filename,data)
        except (ValueError,project_sources.SourceError) as exc:
            fail(getattr(exc,'code','IMPORT_INVALID'),422)
        # Excluded secret bytes are never persisted, echoed or placed in a model prompt.
        row=ImportPreview(id=identity('import'),project_id=project_id,archive_name=payload.filename,
             sha256=result['sha256'],payload_json=encoded(result),created_at=now())
        session.add(row)
        public={**result,'entries':[{k:v for k,v in e.items() if k!='content'} for e in result['entries']]}
        return {'preview_id':row.id,**public}

    @app.post('/api/r2/projects/{project_id}/imports/{preview_id}/confirm')
    def confirm_import(project_id:int,preview_id:str,payload:ImportConfirm,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); owned(session,project_id,user)
        row=session.get(ImportPreview,preview_id)
        if not row or row.project_id!=project_id: fail('IMPORT_NOT_FOUND',404)
        if not payload.confirmation or row.sha256!=payload.sha256: fail('IMPORT_CHANGED')
        names=set(payload.names)
        if len(names)!=len(payload.names) or not names: fail('IMPORT_SELECTION_REQUIRED',422)
        if row.confirmed_at:
            receipt=json.loads(row.receipt_json)
            if set(receipt['selected'])!=names: fail('IMPORT_ALREADY_CONFIRMED')
            return receipt
        result=json.loads(row.payload_json)
        allowed={e['name']:e for e in result['entries'] if e['classification']=='SAFE_IMPORT'}
        if not names<=allowed.keys(): fail('IMPORT_SELECTION_UNSAFE',422)
        for name in sorted(names):
            e=allowed[name]
            old=session.scalar(select(ProjectSource).where(ProjectSource.project_id==project_id,ProjectSource.name==name,ProjectSource.sha256==e['sha256']))
            if not old:
                session.add(ProjectSource(id=identity('source'),project_id=project_id,name=name,sha256=e['sha256'],
                  content=e['content'],language=e['language'],receipt_id=row.id,created_at=now()))
        receipt={'id':row.id,'archive':row.archive_name,'archive_sha256':row.sha256,'selected':sorted(names),
                 'excluded':[e['name'] for e in result['entries'] if e['name'] not in names],
                 'manifest_entries_verified':result['manifest_entries_verified'],'confirmed_at':now(),
                 'canonical_owner_acceptance':'NOT_ASSERTED','full_historical_restoration':False,'credentials_imported':False}
        row.confirmed_at=receipt['confirmed_at']; row.receipt_json=encoded(receipt)
        activity(session,project_id,'SOURCES_IMPORTED',receipt)
        return receipt

    @app.get('/api/r2/projects/{project_id}/sources/{source_id}')
    def read_source(project_id:int,source_id:str,session=Depends(get_db),user=Depends(current_user)):
        owned(session,project_id,user)
        row=session.get(ProjectSource,source_id)
        if not row or row.project_id!=project_id: fail('SOURCE_NOT_FOUND',404)
        return {'id':row.id,'name':row.name,'sha256':row.sha256,'content':row.content,'language':row.language}

    @app.get('/api/r2/tools')
    def tools(session=Depends(get_db),user=Depends(current_user)):
        from .models import AIModel
        connection=preference(session,'wb:connection:'+str(user.id),{})
        return {'candidates':tool_recovery.candidates(settings),'models':connection.get('available_models') or sorted((set(session.scalars(select(AIModel.provider_model_id)).all()) | set(tool_recovery.local_model_catalog()))- {'',None}),
                'model_catalog_evidence':connection.get('model_catalog_evidence','LOCAL_CONFIGURATION_NOT_PROVIDER_READINESS'),
                'provider_contacted':False,'capabilities':{'adapter':'codex_exec','start':True,'status':True,'events':True,'result':True,'cancel':'owned_process_interrupt','resume':'persisted_status_only_no_automatic_reexecution'}}

    @app.post('/api/r2/projects/{project_id}/team')
    def save_team(project_id:int,payload:TeamIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request)
        if session.get_bind().dialect.name=='sqlite': session.execute(text('BEGIN IMMEDIATE'))
        session.expire_all(); space=owned(session,project_id,user)
        candidate=next((x for x in tool_recovery.candidates(settings) if x['id']==payload.tool_id),None)
        if not candidate: fail('EXECUTABLE_MISSING_OR_CHANGED')
        for model in (payload.planner,payload.executor,payload.reviewer):
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}',model): fail('MODEL_REQUIRED',422)
        if not payload.existing_plan_only: fail('BUDGET_REQUIRED',422)
        value=payload.model_dump(); value['executable']=candidate['path']
        value['mode']='SINGLE_MODEL_MULTI_ROLE' if len({payload.planner,payload.executor,payload.reviewer})==1 else 'MULTIPLE_MODELS_CONFIGURED_NOT_VERIFIED'
        value['configuration_hash']=digest(value)
        if json.loads(space.team_json)==value: return value
        space.team_json=encoded(value)
        budget_key=provider_budget_key(session,user.id)
        budget=preference(session,budget_key,{'limit':0,'used':0})
        budget['limit']=None  # provider-owned quotas; old clients may still send request_limit
        save_preference(session,budget_key,budget)
        for w in session.scalars(select(WorkItem).where(WorkItem.project_id==project_id,WorkItem.state.in_(['PLANNED','APPROVED']))):
            w.state='REPLAN_REQUIRED'; w.approval_json='{}'
        activity(session,project_id,'TEAM_SAVED',{'configuration_hash':value['configuration_hash'],'mode':value['mode'],'provider_contacted':False})
        return value

    @app.post('/api/r2/projects/{project_id}/work',status_code=201)
    def create_work(project_id:int,payload:WorkIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); owned(session,project_id,user)
        if payload.output_locale not in LOCALES or not payload.body.strip(): fail('TASK_INPUT_INVALID',422)
        sources=[]
        for sid in sorted(set(payload.source_ids)):
            s=session.get(ProjectSource,sid)
            if not s or s.project_id!=project_id: fail('SOURCE_NOT_FOUND',404)
            sources.append({'id':s.id,'name':s.name,'sha256':s.sha256})
        w=WorkItem(id=identity('work'),project_id=project_id,title=payload.title or payload.body[:70],body=payload.body,
            output_locale=payload.output_locale,sources_json=encoded(sources),created_at=now())
        session.add(w); session.flush()
        activity(session,project_id,'TASK_CREATED',{'body_sha256':digest(w.body),'output_locale':w.output_locale},work_id=w.id)
        return work_out(w)

    @app.post('/api/r2/projects/{project_id}/edit')
    def edit_project(project_id:int,payload:ProjectEditIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request)
        if session.get_bind().dialect.name=='sqlite':session.execute(text('BEGIN IMMEDIATE'))
        session.expire_all();space=owned(session,project_id,user);row=session.get(Project,project_id)
        if payload.expected_digest!=digest({'name':row.name,'goal':space.goal}):fail('PROJECT_CONTEXT_CHANGED')
        if not payload.name.strip():fail('TASK_INPUT_INVALID',422)
        if row.name==payload.name and space.goal==payload.goal:return {'saved':True}
        activity(session,project_id,'PROJECT_CONTEXT_REVISED',{'previous':{'name':row.name,'goal':space.goal},'current':{'name':payload.name,'goal':payload.goal},'source':'USER_CONFIRMED_CURRENT_CONTEXT'})
        row.name=payload.name;space.goal=payload.goal
        for w in session.scalars(select(WorkItem).where(WorkItem.project_id==project_id,WorkItem.state.in_(['PLANNED','APPROVED']))):
            w.state='REPLAN_REQUIRED';w.approval_json='{}'
        return {'saved':True}

    @app.post('/api/r2/work/{work_id}/revise')
    def revise_work(work_id:str,payload:WorkReviseIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request)
        if session.get_bind().dialect.name=='sqlite':session.execute(text('BEGIN IMMEDIATE'))
        session.expire_all();w,space=work_owned(session,work_id,user)
        key='work_revision:'+w.id+':'+payload.request_id;prior=preference(session,key);binding=digest(payload.model_dump())
        if prior:
            if prior['binding']!=binding:fail('IDEMPOTENCY_CONFLICT')
            return prior['result']
        if w.kind!='document' or w.state in ('RUNNING','COMMITTING') or w.revision!=payload.expected_revision:fail('TASK_STATE_CHANGED')
        if payload.output_locale not in LOCALES or not payload.body.strip():fail('TASK_INPUT_INVALID',422)
        sources=[]
        for sid in sorted(set(payload.source_ids)):
            source=session.get(ProjectSource,sid)
            if not source or source.project_id!=w.project_id:fail('SOURCE_NOT_FOUND',404)
            sources.append({'id':source.id,'name':source.name,'sha256':source.sha256})
        activity(session,w.project_id,'TASK_REVISION_ARCHIVED',work_out(w),'user',w.id)
        w.revision+=1;w.title=payload.title or payload.body[:70];w.body=payload.body;w.output_locale=payload.output_locale
        w.sources_json=encoded(sources);w.plan_json='{}';w.plan_hash='';w.approval_json='{}';w.state='DRAFT'
        result=work_out(w);save_preference(session,key,{'binding':binding,'result':result})
        activity(session,w.project_id,'TASK_REVISED',{'revision':w.revision,'body_sha256':digest(w.body),'new_approval_required':True},'user',w.id)
        return result

    @app.post('/api/r2/work/{work_id}/plan')
    def plan_work(work_id:str,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); w,space=work_owned(session,work_id,user)
        if w.kind!='document': fail('ITERATION_ACTION_INVALID',422)
        if w.state not in ('DRAFT','REPLAN_REQUIRED','PLANNED'): fail('TASK_STATE_CHANGED')
        team=json.loads(space.team_json)
        if not team: fail('TEAM_REQUIRED')
        if not any(c['id']==team['tool_id'] for c in tool_recovery.candidates(settings)): fail('EXECUTABLE_MISSING_OR_CHANGED')
        plan={'project_id':w.project_id,'work_id':w.id,'revision':w.revision,'body':w.body,'goal':space.goal,
              'sources':json.loads(w.sources_json),'output_locale':w.output_locale,
              'team_hash':team['configuration_hash'],'model':team['executor'],'team_mode':team['mode'],
              'output_scope':'PROJECT_MANAGED_DOCUMENT','source_write':False,'git_required':False,
              'provider_requests':1,'human_gates':team['human_gates'],'order_authority':'NONE',
              'clinical_authority':'NONE','plan_origin':'DETERMINISTIC_INPUT_SCOPE','recovery_epoch':recovery_epoch(settings)}
        w.plan_json=encoded(plan); w.plan_hash=digest(plan); w.state='PLANNED'; w.approval_json='{}'
        activity(session,w.project_id,'PLAN_PREPARED',{'plan_hash':w.plan_hash,'plan':plan},'system',w.id)
        return work_out(w)

    @app.post('/api/r2/work/{work_id}/approve')
    def approve_work(work_id:str,payload:ApprovalIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); w,space=work_owned(session,work_id,user)
        if w.state not in ('PLANNED','APPROVED') or payload.plan_hash!=w.plan_hash or not payload.confirmation or payload.ui_locale not in LOCALES: fail('APPROVAL_CHANGED')
        plan=json.loads(w.plan_json)
        if plan['team_mode']=='SINGLE_MODEL_MULTI_ROLE' and not payload.single_model_disclosed: fail('SINGLE_MODEL_CONFIRMATION_REQUIRED')
        if not json.loads(w.approval_json):
            w.approval_json=encoded({'actor_id':user.id,'type':'OWNER_APPROVED','plan_hash':w.plan_hash,'ui_locale':payload.ui_locale,
                'displayed_summary':plan,'approved_at':now()})
            activity(session,w.project_id,'PLAN_APPROVED',json.loads(w.approval_json),'user',w.id)
        w.state='APPROVED'
        return work_out(w)

    @app.post('/api/r2/work/{work_id}/start',status_code=202)
    def start_work(work_id:str,payload:StartIn,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); w,space=work_owned(session,work_id,user)
        if w.kind!='document': fail('ITERATION_ACTION_INVALID',422)
        if not payload.confirmation: fail('START_CONFIRMATION_REQUIRED')
        row=service.admit(session,w,space,payload.plan_hash,payload.request_id)
        session.commit(); service.start(row.id)
        return execution_out(row)

    @app.post('/api/r2/work/{work_id}/cancel')
    def cancel_work(work_id:str,request:Request,session=Depends(get_db),user=Depends(current_user)):
        mutation(request); w,space=work_owned(session,work_id,user)
        row=session.scalar(select(WorkExecution).where(WorkExecution.work_id==w.id).order_by(WorkExecution.started_at.desc()))
        if row: service.cancel(row.id)
        return {'cancellation_requested':bool(row),'termination_confirmed':False}

    @app.get('/api/r2/work/{work_id}/export')
    def export_work(work_id:str,execution_id:str|None=None,session=Depends(get_db),user=Depends(current_user)):
        w,space=work_owned(session,work_id,user)
        query=select(WorkExecution).where(WorkExecution.work_id==w.id,WorkExecution.state=='COMPLETED')
        query=query.where(WorkExecution.id==execution_id) if execution_id else query.where(WorkExecution.revision==w.revision)
        row=session.scalar(query.order_by(WorkExecution.started_at.desc()))
        if not row: fail('RESULT_NOT_READY')
        content='# '+w.title+'\n\n'+row.output+'\n\n---\nExecution: '+row.id+'\nSHA-256: '+hashlib.sha256(row.output.encode()).hexdigest()+'\n'
        return Response(content,media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':'attachment; filename="TWOS-result.md"','Cache-Control':'no-store'})

    from .iteration_studio import install as install_studio
    install_studio(app,settings,get_db,current_user,service)
    return service
