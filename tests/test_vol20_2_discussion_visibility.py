"""Public summaries and response failures, using explicit synthetic transports."""
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_vol20_2_workbench import wb, connected, chat, send, wait
from twos_runtime.app import create_app
from twos_runtime.execution_evidence import ExecutionFailure
from twos_runtime.workbench import discussion_activity


def test_activity_only_public_summary_and_known_progress():
    evidence = {}
    for event in [
        {'type': 'item.completed', 'item': {'id': 'r1', 'type': 'reasoning', 'text': 'Public summary', 'content': ['RAW_INTERNAL'], 'encrypted_content': 'ENCRYPTED_INTERNAL'}},
        {'type': 'item.updated', 'item': {'id': 'r1', 'type': 'reasoning', 'text': 'Updated public summary'}},
        {'type': 'item/reasoning/textDelta', 'delta': 'RAW_INTERNAL'},
        {'type': 'twos.progress', 'code': 'UNKNOWN', 'message': 'PRIVATE_DIAGNOSTIC'},
        {'type': 'twos.progress', 'code': 'CLI_RECONNECTING', 'message': 'PRIVATE_DIAGNOSTIC'},
    ]:
        evidence = discussion_activity(evidence, event)
    assert [x['kind'] for x in evidence['public_activity']] == ['summary', 'status']
    assert evidence['public_activity'][0]['text'] == 'Updated public summary'
    assert 'RAW_INTERNAL' not in json.dumps(evidence)
    assert 'PRIVATE_DIAGNOSTIC' not in json.dumps(evidence)
    assert 'ENCRYPTED_INTERNAL' not in json.dumps(evidence)
    assert discussion_activity(evidence, {'type': 'item.completed', 'item': {'id': 'r2', 'type': 'reasoning', 'content': ['RAW_INTERNAL']}}) == evidence


@pytest.mark.parametrize('finish', ['success', 'failure', 'cancel'])
def test_public_summary_visible_live_and_preserved_after_terminal_and_restart(wb, finish):
    c = connected(wb); app = wb[1]; cid = chat(c)
    ready, release = threading.Event(), threading.Event()
    def model(*args, **options):
        callback = options['on_event']
        callback({'type': 'turn.started'})
        callback({'type': 'item.updated', 'item': {'id': 'summary-1', 'type': 'reasoning', 'text': 'Checking the requested mobile layout'}})
        callback({'type': 'item.completed', 'item': {'id': 'partial-1', 'type': 'agent_message', 'text': 'Partial answer'}})
        ready.set()
        assert release.wait(5)
        if finish == 'failure': raise ExecutionFailure('PROVIDER_CONNECTION_FAILED', {'duration_seconds': 2.5})
        return 'Final answer', {'test_double': True}
    app.state.discussion.runner = model
    assert send(c, cid).status_code == 202
    try:
        assert ready.wait(5)
        message = c.get(f'/api/r2/wb/chats/{cid}').json()['messages'][-1]
        assert message['state'] == 'RUNNING' and message['body'] == 'Partial answer'
        assert message['evidence']['public_activity'][-1]['text'] == 'Checking the requested mobile layout'
        if finish == 'cancel': assert c.post(f'/api/r2/wb/chats/{cid}/cancel', json={}).status_code == 200
    finally:
        release.set()
    message = wait(c, cid)['messages'][-1]
    assert message['state'] == {'success': 'COMPLETED', 'failure': 'FAILED', 'cancel': 'CANCELLED'}[finish]
    assert message['evidence']['public_activity'][-1]['text'] == 'Checking the requested mobile layout'
    assert message['body'] == ('Final answer' if finish == 'success' else 'Partial answer')
    assert message['client'] == '/synthetic/codex'
    with TestClient(create_app(wb[3], start_scheduler=False)) as restarted:
        restarted.cookies.update(dict(c.cookies))
        assert restarted.get(f'/api/r2/wb/chats/{cid}').json()['messages'][-1] == message
        assert not restarted.app.state.discussion.jobs


@pytest.mark.parametrize('supported', [False, True])
def test_legacy_client_catalog_checked_before_any_model_request(wb, monkeypatch, supported):
    import twos_runtime.workbench as module
    from twos_runtime import workbench_codex
    c = connected(wb); cid = chat(c); calls = []
    def catalog(executable, root):
        calls.append(('catalog', executable))
        return ['synthetic-model'] if supported else ['different-model']
    def provider(*args, **options):
        calls.append(('provider', args[0])); return 'Validated response', {'test_double': True}
    monkeypatch.setattr(workbench_codex, 'advertised_models', catalog)
    monkeypatch.setattr(module, 'codex_document', provider)
    wb[1].state.discussion.runner = provider
    assert send(c, cid).status_code == 202
    message = wait(c, cid)['messages'][-1]
    assert calls == [('catalog', '/synthetic/codex')] + ([('provider', '/synthetic/codex')] if supported else [])
    if supported:
        assert message['state'] == 'COMPLETED'
    else:
        assert message['state'] == 'FAILED'
        assert message['evidence']['error_code'] == 'MODEL_NOT_ADVERTISED'
        assert message['evidence']['cli_invocations'] == 0
        assert message['evidence']['requested_model'] == 'synthetic-model'


def test_native_exec_forwards_public_summary_and_classified_reconnection(tmp_path):
    from twos_runtime.project_execution import codex_document
    import sys
    executable = tmp_path/'synthetic-codex'
    executable.write_text('#!'+sys.executable+'\n'+'''import sys,json,pathlib
assert 'show_raw_agent_reasoning=false' in sys.argv
assert 'model_reasoning_summary="auto"' in sys.argv
sys.stdin.read()
events=[{'type':'thread.started','thread_id':'synthetic-thread'}, {'type':'turn.started'},
 {'type':'error','message':'Reconnecting... 1/5 (stream disconnected)'},
 {'type':'item.completed','item':{'id':'transport','type':'error','message':'Falling back from WebSockets to HTTPS transport. fixture'}},
 {'type':'item.completed','item':{'id':'summary','type':'reasoning','text':'Public summary'}},
 {'type':'item.completed','item':{'id':'final','type':'agent_message','text':'Final reply'}},
 {'type':'turn.completed'}]
pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('Final reply')
for event in events: print(json.dumps(event),flush=True)
''')
    executable.chmod(0o700)
    cwd=tmp_path/'work';cwd.mkdir();events=[]
    output,evidence=codex_document(str(executable),'synthetic-model','Synthetic input',cwd,threading.Event(),lambda _:None,native_provider=True,on_event=events.append)
    assert output == 'Final reply'
    assert evidence['warning_codes'] == ['CLI_RECONNECTING','CLI_HTTPS_TRANSPORT_RECOVERY']
    assert [x['code'] for x in events if x['type']=='twos.progress'] == evidence['warning_codes']
    assert any(x.get('item',{}).get('text') == 'Public summary' for x in events)
    assert not any(x['type']=='error' for x in events)
