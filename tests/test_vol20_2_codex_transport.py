"""Protocol behavior without provider requests; real execution is separately recorded."""
from pathlib import Path
import threading
from twos_runtime.workbench_codex import AppServer,isolated_environment


def bare():
    t=AppServer.__new__(AppServer);t.thread_id='thread-1';t.turn_id='turn-1';t.responses={};t.items={};t.completed=None;t.pending=set();t.tool_actions=0
    messages=[];events=[];t.send=messages.append;t.emit=lambda kind,payload:events.append((kind,payload))
    return t,messages,events


def test_bound_protocol_events_and_no_reasoning_exposure():
    t,sent,events=bare()
    t.accept({'method':'item/completed','params':{'threadId':'other','item':{'id':'x','type':'agentMessage','text':'wrong account'}}})
    assert not t.items and not events
    t.accept({'method':'item/completed','params':{'threadId':'thread-1','item':{'id':'r','type':'reasoning','text':'private reasoning'}}})
    assert not events
    t.accept({'id':22,'method':'item/permissions/requestApproval','params':{'threadId':'thread-1','turnId':'old'}})
    assert sent[-1]['error']['message']=='Stale turn' and not t.pending
    t.accept({'id':23,'method':'item/permissions/requestApproval','params':{'threadId':'thread-1','turnId':'turn-1','permissions':{'network':{'enabled':True}}}})
    assert t.pending=={23} and events[-1][0]=='approval'
    t.accept({'id':24,'method':'unknown/request','params':{'threadId':'thread-1'}})
    assert sent[-1]['error']['code']==-32601


def test_turn_connects_real_local_environment_and_uses_saved_thread(tmp_path):
    t,sent,events=bare();requests=[]
    def request(method,params):
        requests.append((method,params))
        if method=='thread/resume':return {'thread':{'id':'thread-1'},'model':'gpt-6.1-sol'}
        if method=='turn/start':return {'turn':{'id':'turn-2'}}
        return {}
    t.request=request
    def pump():
        t.accept({'method':'item/completed','params':{'threadId':'thread-1','turnId':'turn-2','item':{'id':'cmd','type':'commandExecution','exitCode':0}}})
        t.accept({'method':'item/completed','params':{'threadId':'thread-1','turnId':'turn-2','item':{'id':'final','type':'agentMessage','phase':'final_answer','text':'Actual result'}}})
        t.accept({'method':'turn/completed','params':{'threadId':'thread-1','turn':{'id':'turn-2','status':'completed'}}})
    t.pump=pump
    output,proof=t.run(model='gpt-6.1-sol',prompt='Build the approved page',cwd=tmp_path,thread_id='thread-1')
    params=dict(requests)['turn/start']
    assert params['environments']==[{'environmentId':'local','cwd':str(tmp_path),'runtimeWorkspaceRoots':[str(tmp_path)]}]
    assert params['permissions']=='twos-project' and params['approvalPolicy']['granular']['sandbox_approval'] is False
    assert 'environments' not in dict(requests)['thread/resume']
    assert output=='Actual result' and proof['tool_actions']==1


def test_isolated_profiles_use_project_scratch_and_no_global_credentials_in_tools(tmp_path,monkeypatch):
    import tomllib
    monkeypatch.setattr('twos_runtime.workbench_codex.codex_child_environment',lambda:{'HOME':str(tmp_path/'empty-home'),'PATH':'/usr/bin:/bin','OPENAI_API_KEY':'synthetic-secret'})
    project=tmp_path/'project';project.mkdir(mode=0o700)
    home=tmp_path/'isolated-codex';env=isolated_environment(home,project)
    cfg=tomllib.loads((home/'config.toml').read_text())
    assert 'OPENAI_API_KEY' not in env and env['TMPDIR']==str(project/'.twos/tmp')
    assert cfg['permissions']['twos-project']['network']['enabled'] is False
    assert cfg['permissions']['twos-review']['filesystem'][':workspace_roots']=='read'
    assert cfg['permissions']['twos-review']['filesystem'][env['TMPDIR']]=='write'
    assert cfg['allow_login_shell'] is False and not cfg['features']['multi_agent']
    assert cfg['permissions']['twos-project']['filesystem'][':root']=='deny'
    assert cfg['permissions']['twos-project']['filesystem'][':slash_tmp']=='deny'
    assert cfg['permissions']['twos-review']['filesystem'][str(project/'.codex')]=='deny'


def test_stale_turn_output_does_not_change_current_delivery():
    t,sent,events=bare()
    t.accept({'method':'item/completed','params':{'threadId':'thread-1','turnId':'old','item':{'id':'bad','type':'agentMessage','text':'stale'}}})
    assert not events and not t.items


def test_native_reconnection_requires_real_success_not_just_an_advisory(tmp_path):
    import pytest
    from tests.test_vol20_r2_final_channel import invoke,body
    from twos_runtime.execution_evidence import ExecutionFailure
    advisory='print(json.dumps({"type":"error","message":"Reconnecting... 2/5 (request timed out)"}),flush=True)\n'
    advisory+='print(json.dumps({"type":"item.completed","item":{"id":"transport","type":"error","message":"Falling back from WebSockets to HTTPS transport. request timed out"}}),flush=True)\n'
    finish=body(tail='print(json.dumps({"type":"turn.completed"}))\n')
    output,proof=invoke(tmp_path,advisory+finish,native_provider=True)
    assert output=='final' and 'CLI_RECONNECTING' in proof['warning_codes']
    assert proof['transport_retry_configuration']['policy']=='INSTALLED_CODEX_NATIVE_BOUNDED_RECOVERY'
    other=tmp_path/'failed';other.mkdir()
    with pytest.raises(ExecutionFailure):invoke(other,advisory+body(),native_provider=True)
    terminal=tmp_path/'terminal';terminal.mkdir()
    with pytest.raises(ExecutionFailure):invoke(terminal,'print(json.dumps({"type":"turn.failed","error":{"message":"connection reset"}}))\n'+finish,native_provider=True)
    legacy=tmp_path/'legacy';legacy.mkdir()
    with pytest.raises(ExecutionFailure):invoke(legacy,advisory+finish)


def test_selected_client_catalog_never_starts_a_model_turn(tmp_path,monkeypatch):
    from twos_runtime import workbench_codex as transport
    methods=[]
    class Catalog:
        def __init__(self,*a):pass
        def send(self,value):methods.append(value['method'])
        def request(self,method,params):
            methods.append(method)
            if method=='model/list':return {'data':[{'model':'gpt-6.1-sol'}],'nextCursor':None}
            return {}
        def close(self):methods.append('close')
    monkeypatch.setattr(transport,'AppServer',Catalog)
    assert transport.advertised_models('/synthetic/client',tmp_path)==['gpt-6.1-sol']
    assert methods==['initialize','initialized','model/list','close']
