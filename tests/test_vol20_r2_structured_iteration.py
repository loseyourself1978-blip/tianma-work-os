"""Offline fixtures exercise the protected patch channel, never a real model."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import sys

import pytest
from fastapi import HTTPException
from twos_runtime import iteration_studio as studio
from tests.test_vol20_r2_project_first import product, project, team, task


@pytest.fixture
def source(tmp_path):
    root=tmp_path/'source';root.mkdir()
    files={studio.CATALOG:json.dumps({'noSourcesDesc':{'en-US':'Original fixture text','zh-CN':'原始替身内容'},'guard':{'en-US':'unchanged','zh-CN':'不变'}}),
           'twos_runtime/app.py':'# synthetic fixture', 'scripts/build_macos.py':'# never run', 'tests/.keep':''}
    for name,data in files.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data)
    for args in [('init','-b','main'),('add','.'),('commit','-m','Synthetic offline fixture')]:
        studio.git(root,'-c','user.name=Synthetic','-c','user.email=fixture@example.invalid',*args)
    return root,studio.git(root,'rev-parse','HEAD').strip()


def patch(root,baseline):
    return {'schema':studio.PATCH_SCHEMA,'baseline':baseline,'catalog_sha256':hashlib.sha256((root/studio.CATALOG).read_bytes()).hexdigest(),
            'replacement':{'en-US':'Synthetic fixture changed','zh-CN':'合成替身已改变'},
            'regression':'''import json
from pathlib import Path
import unittest
class Fixture(unittest.TestCase):
    def test_pair(self):
        data=json.loads((Path(__file__).resolve().parents[1]/"static_cockpit/project_first/catalog.json").read_text())
        self.assertEqual(data["noSourcesDesc"], {"en-US":"Synthetic fixture changed","zh-CN":"合成替身已改变"})
        self.assertEqual(data["guard"]["en-US"], "unchanged")
''','summary':'Offline synthetic transport fixture, not the actual iteration patch.'}


def invariant(root):
    return {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('.git/HEAD','.git/index','.git/config')}


def test_subprocess_response_applies_exact_patch_and_runs_real_deterministic_test(source,tmp_path):
    from twos_runtime.project_execution import codex_document
    root,baseline=source;before=invariant(root);value=patch(root,baseline)
    executable=tmp_path/'substitute'
    executable.write_text('#!'+sys.executable+'\nimport sys,json\n'
        'print(json.dumps({"type":"thread.started","thread_id":"fixture-thread"}))\nprint(json.dumps({"type":"turn.started"}))\n'
        'assert sys.argv[sys.argv.index("--sandbox")+1]=="read-only"\n'
        'assert "features.shell_tool=false" in sys.argv\n'
        'assert "features.unbounded_connection_retries=false" in sys.argv\n'
        'assert "approved fixture" in sys.stdin.read()\n'
        'from pathlib import Path\nPath(sys.argv[sys.argv.index("--output-last-message")+1]).write_text('+repr(json.dumps(value))+')\n'
        'print(json.dumps({"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":'+repr(json.dumps(value))+'}}))\n'
        'print(json.dumps({"type":"turn.completed"}))\n')
    executable.chmod(0o700)
    output,evidence=codex_document(str(executable),'substitute','approved fixture',root,threading.Event(),lambda _:None)
    assert not (root/studio.REGRESSION).exists()  # subprocess cannot be credited with disk writes
    receipt=studio.apply_structured_patch(root,baseline,output)
    checks=studio.check_changes(root,baseline)
    assert receipt['model_filesystem_write'] is False and set(checks['scope'])==set(studio.ALLOWED)
    assert invariant(root)==before and evidence['cli_invocations']==1
    # Actual Python executes this synthetic regression; no provider substitute PASS.
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p',Path(studio.REGRESSION).name],cwd=root,capture_output=True)
    assert result.returncode==0,result.stderr
    app=os.environ.get('TWOS_TEST_MACOS_APP')
    if app:
        from twos_runtime.iteration_candidate import run_regression
        assert run_regression(root,Path(app))=={'tests_run':1,'passed':True,'failures':0,'errors':0,'sandbox':'read-only-no-network'}
        # Real sandbox negative checks use a public test file, never credentials.
        extra='''
    def test_security(self):
        import socket, subprocess
        with self.assertRaises(PermissionError):
            Path(PUBLIC_TEST_FILE).read_bytes()
        with self.assertRaises(PermissionError):
            Path(__file__).write_text("forbidden")
        with self.assertRaises(PermissionError):
            socket.create_connection(("127.0.0.1",9),timeout=1)
        with self.assertRaises(PermissionError):
            subprocess.run(["/bin/echo","forbidden"],check=True)
'''.replace('PUBLIC_TEST_FILE',repr(str(Path(__file__).resolve())))
        with (root/studio.REGRESSION).open('a') as stream:stream.write(extra)
        assert run_regression(root,Path(app))['tests_run']==2


@pytest.mark.parametrize('case,code',[
    ('format','ITERATION_PATCH_FORMAT_INVALID'),('duplicate','ITERATION_PATCH_FORMAT_INVALID'),
    ('extra_path','ITERATION_PATCH_FORMAT_INVALID'),('stale','DEVELOPMENT_TARGET_CHANGED'),
    ('baseline','DEVELOPMENT_TARGET_CHANGED'),('unchanged','ITERATION_NO_CHANGES'),
    ('locale','ITERATION_TRANSLATION_INVALID'),('empty_test','ITERATION_REGRESSION_REQUIRED'),
    ('double_escaped_test','ITERATION_REGRESSION_INVALID'),
    ('dirty','DEVELOPMENT_SOURCE_DIRTY'),('symlink','DEVELOPMENT_PATH_UNSAFE'),('hardlink','ITERATION_SCOPE_VIOLATION'),
    ('write_failure','ITERATION_PATCH_WRITE_FAILED')])
def test_patch_fail_closed_preserves_repository(source,tmp_path,monkeypatch,case,code):
    root,baseline=source;value=patch(root,baseline);catalog=root/studio.CATALOG
    if case=='extra_path':value['path']='../../owner'
    if case=='stale':value['catalog_sha256']='0'*64
    if case=='baseline':value['baseline']='0'*40
    if case=='unchanged':value['replacement']=json.loads(catalog.read_text())['noSourcesDesc']
    if case=='locale':value['replacement']['zh-CN']=''
    if case=='empty_test':value['regression']=''
    if case=='double_escaped_test':value['regression']=value['regression'].replace('\n','\\n')
    if case=='dirty':(root/'unapproved').write_text('kept')
    if case=='symlink':
        saved=tmp_path/'preserved';catalog.rename(saved);catalog.symlink_to(saved)
    if case=='hardlink':os.link(catalog,tmp_path/'preserved')
    if case=='write_failure':monkeypatch.setattr(studio.os,'link',lambda *a: (_ for _ in ()).throw(OSError('synthetic lock conflict')))
    before=catalog.read_bytes();git_before=invariant(root)
    output=json.dumps(value)
    if case=='format':output='not JSON'
    if case=='duplicate':output=output[:-1]+',"schema":"duplicate"}'
    with pytest.raises(HTTPException) as exc:studio.apply_structured_patch(root,baseline,output)
    assert exc.value.detail['code']==code
    assert catalog.read_bytes()==before and invariant(root)==git_before
    assert not (root/studio.REGRESSION).exists()


def test_new_regression_parent_is_created_inside_approved_target(source):
    root,_=source
    studio.git(root,'rm','tests/.keep')
    studio.git(root,'-c','user.name=Synthetic','-c','user.email=fixture@example.invalid','commit','-m','Fixture without a tests directory')
    assert not (root/'tests').exists()
    baseline=studio.git(root,'rev-parse','HEAD').strip()
    studio.apply_structured_patch(root,baseline,json.dumps(patch(root,baseline)))
    assert set(studio.check_changes(root,baseline)['scope'])==set(studio.ALLOWED)
    result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p',Path(studio.REGRESSION).name],cwd=root,capture_output=True)
    assert result.returncode==0,result.stderr


def test_unused_target_rebinding_retains_history_and_budget(product,source):
    c,app,_=product;root,baseline=source;pid=project(c,'Unused target','development');team(c,pid)
    def bind():
        r=c.post(f'/api/r2/projects/{pid}/target/preview',json={'path':str(root)})
        assert r.status_code==200,r.text
        b={'preview_hash':r.json()['preview_hash'],'confirmation':True}
        result=c.post(f'/api/r2/projects/{pid}/target/confirm',json=b)
        assert result.status_code==200,result.text
        assert c.post(f'/api/r2/projects/{pid}/target/confirm',json=b).json()==result.json()
        return result.json()
    first=bind();budget=c.get(f'/api/r2/projects/{pid}').json()['request_budget']
    (root/'docs').mkdir();(root/'docs/fixture').write_text('another source identity')
    studio.git(root,'add','.');studio.git(root,'-c','user.name=Synthetic','-c','user.email=fixture@example.invalid','commit','-m','Fixture second identity')
    second=bind()
    assert second['snapshot']!=first['snapshot'] and second['previous_snapshot_preserved']==first['snapshot']
    assert studio.git(Path(first['snapshot']),'rev-parse','HEAD').strip()==baseline
    assert c.get(f'/api/r2/projects/{pid}').json()['request_budget']==budget and app.state.project_execution.jobs=={}
    task(c,pid)
    (root/'docs/fixture').write_text('third identity');studio.git(root,'add','.')
    studio.git(root,'-c','user.name=Synthetic','-c','user.email=fixture@example.invalid','commit','-m','Fixture third identity')
    r=c.post(f'/api/r2/projects/{pid}/target/preview',json={'path':str(root)})
    assert r.status_code==409 and r.json()['error']['code']=='DEVELOPMENT_TARGET_IN_USE'
    assert c.get(f'/api/r2/projects/{pid}').json()['target']==second


@pytest.mark.parametrize('invalid',['missing','failed','zero','stale','wrong_plan'])
def test_independent_review_requires_actual_matching_test_receipt(source,invalid):
    from types import SimpleNamespace
    root,baseline=source
    studio.apply_structured_patch(root,baseline,json.dumps(patch(root,baseline)))
    checks=studio.check_changes(root,baseline)
    evidence={'deterministic_checks':checks,'regression':{'passed':True,'tests_run':1}}
    row=SimpleNamespace(id='synthetic-executor',plan_hash='exact-plan',evidence_json=json.dumps(evidence))
    work=SimpleNamespace(id='fixture-work',revision=1,plan_hash='exact-plan')
    rows=[row]
    session=SimpleNamespace(scalars=lambda _:rows)
    assert studio.executed_regression(session,work,root,baseline)['executor_id']==row.id
    if invalid=='missing':rows.clear()
    if invalid=='failed':evidence['regression']['passed']=False
    if invalid=='zero':evidence['regression']['tests_run']=0
    if invalid=='stale':evidence['deterministic_checks']['files']={}
    if invalid=='wrong_plan':row.plan_hash='unapproved-plan'
    row.evidence_json=json.dumps(evidence)
    with pytest.raises(HTTPException) as exc:studio.executed_regression(session,work,root,baseline)
    assert exc.value.detail['code']=='ITERATION_TEST_EVIDENCE_REQUIRED'
