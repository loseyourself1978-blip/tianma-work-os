"""Controller terminal states; synthetic runner, zero provider invocations."""
import json
import time

import pytest
from fastapi.testclient import TestClient

from tests.test_vol20_r2_project_first import product, project, team
from tests.test_vol20_r2_structured_iteration import source, patch
from tests.test_vol19_fresh_install_first_run import USERNAME, PASSWORD
from twos_runtime.app import create_app
from twos_runtime.execution_evidence import ExecutionFailure
from twos_runtime import iteration_studio as studio, iteration_candidate


@pytest.mark.parametrize('case', ['pass', 'negative_verdict', 'invalid_schema', 'empty_reason', 'extraction_failure', 'nonzero'])
def test_reviewer_truthful_terminal_survives_reload(product,source,monkeypatch,tmp_path,case):
    c,app,settings=product;root,baseline=source;pid=project(c,'Reviewer terminal '+case,'development');team(c,pid)
    preview=c.post(f'/api/r2/projects/{pid}/target/preview',json={'path':str(root)}).json()
    assert c.post(f'/api/r2/projects/{pid}/target/confirm',json={'preview_hash':preview['preview_hash'],'confirmation':True}).status_code==200
    # This test isolates controller state, not generated-test correctness.
    monkeypatch.setattr(iteration_candidate,'bundle_path',lambda:tmp_path/'synthetic-app')
    monkeypatch.setattr(iteration_candidate,'run_regression',lambda *a:{'passed':True,'tests_run':1,'test_substitute':True})
    monkeypatch.setattr(iteration_candidate,'validate_generated_regression',lambda *a:{'status':'PASSED','test_substitute':True})
    calls=[]
    def runner(executable,model,prompt,cwd,cancel,on_process,**options):
        calls.append('reviewer' if 'Review this actual diff' in prompt else 'executor' if 'EXECUTION_PATCH_RESPONSE' in prompt else 'planner')
        evidence={'test_substitute':True,'cli_invocations':0,'final_result_extraction':'PASSED',
                  'schema_validation':'PENDING_CONTROLLER' if options.get('output_schema') else 'NOT_APPLICABLE'}
        if calls[-1]=='executor':return json.dumps(patch(cwd,baseline)),evidence
        if calls[-1]=='planner':return 'Synthetic bounded plan',evidence
        if case in ('extraction_failure','nonzero'):
            raise ExecutionFailure('RESULT_FINAL_AMBIGUOUS' if case=='extraction_failure' else 'EXECUTION_INCOMPLETE',
                                   {**evidence,'final_result_extraction':'NOT_REACHED','schema_validation':'NOT_REACHED','exit_code':0 if case=='extraction_failure' else 1})
        value={'verdict':'FAIL' if case=='negative_verdict' else 'PASS','reason':'Synthetic independent review.'}
        if case=='invalid_schema':value['unexpected']='rejected'
        if case=='empty_reason':value['reason']=' '
        return json.dumps(value),evidence
    app.state.project_execution.runner=runner
    def settle():
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            d=c.get(f'/api/r2/projects/{pid}').json()
            if d['works'] and d['works'][-1]['state']!='RUNNING':return d
            time.sleep(.02)
        raise AssertionError('controller did not settle')
    r=c.post(f'/api/r2/projects/{pid}/iterations',json={'body':'Improve bilingual source guidance','output_locale':'en-US','request_id':'terminal-plan','confirmation':True})
    assert r.status_code==202,r.text
    w=settle()['works'][-1]
    assert c.post(f"/api/r2/work/{w['id']}/approve",json={'plan_hash':w['plan_hash'],'ui_locale':'en-US','confirmation':True,'single_model_disclosed':True}).status_code==200
    action={'plan_hash':w['plan_hash'],'request_id':'terminal-execute','confirmation':True}
    assert c.post(f"/api/r2/iterations/{w['id']}/execute",json=action).status_code==202
    assert settle()['works'][-1]['state']=='BUILT'
    review=c.post(f"/api/r2/iterations/{w['id']}/review",json={**action,'request_id':'terminal-review'})
    assert review.status_code==202,review.text
    d=settle();row=next(e for e in d['executions'] if e['id']==review.json()['id'])
    expected='PASSED' if case in ('pass','negative_verdict') else 'NOT_REACHED' if case in ('extraction_failure','nonzero') else 'FAILED'
    assert row['evidence']['schema_validation']==expected
    assert row['evidence']['validation']==('PASSED' if expected=='PASSED' else 'FAILED')
    assert row['state']==('COMPLETED' if expected=='PASSED' else 'FAILED')
    assert d['works'][-1]['state']==('REVIEWED' if case=='pass' else 'REVIEW_FAILED' if case=='negative_verdict' else 'FAILED')
    assert bool(row['evidence'].get('independent_review')) is (expected=='PASSED')
    assert calls==['planner','executor','reviewer']
    # New application/session reads the persisted terminal state, without a retry.
    with TestClient(create_app(settings,start_scheduler=False)) as reloaded:
        assert reloaded.post('/api/auth/login',json={'username':USERNAME,'password':PASSWORD}).status_code==200
        again=reloaded.get(f'/api/r2/projects/{pid}').json()
        assert next(e for e in again['executions'] if e['id']==row['id'])==row
        assert reloaded.app.state.project_execution.jobs=={}
