"""Installed CLI protocol evidence, without credentials, inference, or Owner state.

Unlike the deterministic native-client tests this starts two real app-server
processes in one newly created test CODEX_HOME to exercise their writer lease.
"""
from pathlib import Path
import json
import os
import queue
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest

CLI = Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex')
pytestmark = pytest.mark.skipif(not CLI.is_file(), reason='Installed macOS Codex CLI required')
PROFILE = 'permissions.twos-test.filesystem={":root"="deny",":minimal"="read",":workspace_roots"={"."="write",".git"="read",".codex"="deny",".aws"="deny",".ssh"="deny",".env"="deny"}}'

class Server:
    def __init__(self, root, suffix, overrides=(), env_updates=None):
        self.sequence = 0
        self.messages = queue.Queue()
        self.events = []
        self.stderr = (root / ('server-' + suffix + '.log')).open('w')
        env = dict(os.environ, CODEX_HOME=str(root / 'home'))
        env.update(env_updates or {})
        for key in ('OPENAI_API_KEY', 'CODEX_ACCESS_TOKEN'):
            env.pop(key, None)
        args = [str(CLI), 'app-server', '--listen', 'stdio://']
        for override in ('features.apps=false', 'features.plugins=false', 'features.multi_agent=false', 'mcp_servers={}',
                         'default_permissions="twos-test"', PROFILE, 'permissions.twos-test.network.enabled=false', *overrides):
            args += ['-c', override]
        self.process = subprocess.Popen(args, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True, bufsize=1)
        def read():
            try:
                for line in self.process.stdout:
                    self.messages.put(json.loads(line))
            finally:
                self.messages.put({'closed': True})
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        response = self.call('initialize', {'clientInfo': {'name': 'twos_handoff_protocol_test', 'version': '1'}, 'capabilities': {'experimentalApi': True}})
        assert 'result' in response, response

    def call(self, method, params):
        self.sequence += 1
        self.process.stdin.write(json.dumps({'id': self.sequence, 'method': method, 'params': params}) + '\n')
        self.process.stdin.flush()
        while True:
            message = self.messages.get(timeout=25)
            assert not message.get('closed'), 'Isolated protocol server closed'
            if message.get('id') == self.sequence:
                return message
            self.events.append(message)

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()  # Only this credential-free, inference-free fixture.
                self.process.wait(timeout=5)
        self.reader.join(timeout=1)
        self.stderr.close()


def test_real_writer_lease_canonical_scope_and_restart(tmp_path):
    (tmp_path/'home').mkdir()
    workspace = tmp_path/'plain-empty-folder'
    workspace.mkdir()
    workspace = workspace.resolve()
    first = second = None
    try:
        first = Server(tmp_path, 'first')
        result = first.call('thread/start', {
            'cwd': str(workspace), 'runtimeWorkspaceRoots': [str(workspace)],
            'environments': [{'environmentId': 'local', 'cwd': str(workspace), 'runtimeWorkspaceRoots': [str(workspace)]}],
            'permissions': 'twos-test', 'approvalPolicy': 'on-request', 'approvalsReviewer': 'user',
            'historyMode': 'paginated', 'model': 'gpt-6.1-sol', 'allowProviderModelFallback': False,
        })['result']
        tid = result['thread']['id']
        assert result['cwd'] == str(workspace)
        assert result['runtimeWorkspaceRoots'] == [str(workspace)]
        assert result['activePermissionProfile']['id'] == 'twos-test'
        assert result['sandbox']['networkAccess'] is False
        assert result['sandbox']['excludeSlashTmp'] is True
        assert result['sandbox']['excludeTmpdirEnvVar'] is True
        assert result['thread']['canAcceptDirectInput'] is True
        assert 'result' in first.call('thread/name/set', {'threadId': tid, 'name': 'Isolated writer-lease fixture'})
        second = Server(tmp_path, 'second')
        history = second.call('thread/read', {'threadId': tid, 'includeTurns': False})['result']['thread']
        assert history['status']['type'] == 'notLoaded', 'Stored history is not global execution state'
        denied = second.call('thread/resume', {'threadId': tid, 'excludeTurns': True})
        assert 'active writer' in denied['error']['message']
        first.close()
        first = None
        resumed = second.call('thread/resume', {'threadId': tid, 'excludeTurns': True,
                                               'permissions': 'twos-test', 'runtimeWorkspaceRoots': [str(workspace)]})['result']
        assert resumed['thread']['id'] == tid
        assert resumed['thread']['status']['type'] == 'idle'
        assert resumed['runtimeWorkspaceRoots'] == [str(workspace)]
        effective = second.call('thread/read', {'threadId': tid, 'includeTurns': False})['result']['thread']
        assert effective['id'] == tid and effective['cwd'] == str(workspace)
        assert effective['historyMode'] == 'paginated' and effective['status']['type'] == 'idle'
        if effective.get('environments') is not None:
            assert effective['environments'] == [{'environmentId': 'local', 'cwd': str(workspace), 'runtimeWorkspaceRoots': [str(workspace)]}]
        assert list(workspace.iterdir()) == [], 'No Git initialization or sample output is allowed'
        assert not any(event.get('method') == 'turn/started' for event in second.events)
    finally:
        if second:
            second.close()
        if first:
            first.close()


def test_installed_schema_confirms_expected_turn_and_queue_limits(tmp_path):
    schema = tmp_path/'schema'
    result = subprocess.run([str(CLI), 'app-server', 'generate-json-schema', '--experimental', '--out', str(schema)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    steer = json.loads((schema/'v2/TurnSteerParams.json').read_text())
    assert {'threadId', 'input', 'expectedTurnId'} <= set(steer['required'])
    assert not {'model', 'cwd', 'permissions', 'effort'} & set(steer['properties'])
    queued = json.loads((schema/'v2/ThreadQueueAddParams.json').read_text())
    assert {'threadId', 'input', 'clientUserMessageId'} <= set(queued['required'])
    # There is no per-item settings/pause snapshot. TWOS must defer in durable
    # state, verify the next-turn settings, then expose one eligible entry.
    assert not {'model', 'effort', 'paused'} & set(queued['properties'])


def test_real_cold_queue_requires_exact_start_and_does_not_replay(tmp_path):
    """Real installed queue protocol; synthetic Responses served only on loopback.

    This is protocol evidence, not a real model or business execution PASS.
    No credentials, Owner state, external network, tools or workspace writes.
    """
    requests = []
    received = threading.Event()
    release = threading.Event()
    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            received.set()
            release.wait(timeout=10)
            message = {'id': 'msg_local_fixture', 'type': 'message', 'role': 'assistant',
                       'status': 'completed', 'content': [{'type': 'output_text', 'text': 'LOCAL_PROTOCOL_FIXTURE', 'annotations': []}]}
            events = [
                {'type': 'response.created', 'response': {'id': 'resp_local_fixture'}},
                {'type': 'response.output_item.added', 'output_index': 0, 'item': message},
                {'type': 'response.output_item.done', 'output_index': 0, 'item': message},
                {'type': 'response.completed', 'response': {'id': 'resp_local_fixture', 'status': 'completed',
                    'output': [message], 'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}},
            ]
            body = ''.join('event: '+e['type']+'\ndata: '+json.dumps(e)+'\n\n' for e in events).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The interrupted seed request has no live consumer.

    http = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    serving = threading.Thread(target=http.serve_forever, daemon=True)
    serving.start()
    overrides = ('model_provider="twos_local_fixture"',
                 'model_providers.twos_local_fixture={name="TWOS protocol fixture",base_url="http://127.0.0.1:'+str(http.server_port)+'/v1",wire_api="responses",requires_openai_auth=false,supports_websockets=false,request_max_retries=0,stream_max_retries=0}')
    (tmp_path/'home').mkdir()
    workspace = tmp_path/'empty-workspace'
    workspace.mkdir()
    workspace = workspace.resolve()
    first = second = observer = None
    try:
        local_env = {'NO_PROXY': '127.0.0.1,localhost', 'no_proxy': '127.0.0.1,localhost'}
        first = Server(tmp_path, 'create-cold', overrides, local_env)
        tid = first.call('thread/start', {'cwd': str(workspace), 'runtimeWorkspaceRoots': [str(workspace)],
            'permissions': 'twos-test', 'historyMode': 'paginated', 'model': 'gpt-6.1-sol'})['result']['thread']['id']
        assert 'result' in first.call('thread/name/set', {'threadId': tid, 'name': 'Cold queue protocol fixture'})
        seed = first.call('turn/start', {'threadId': tid, 'input': [{'type': 'text', 'text': 'Interrupted local fixture seed.'}]})['result']['turn']
        assert received.wait(timeout=5), 'Local synthetic provider did not receive the seed'
        # Match the actual installed version's observer projection without
        # resuming, steering or taking over the active writer connection.
        observer = Server(tmp_path, 'active-observer', overrides, local_env)
        projected = observer.call('thread/turns/list', {'threadId': tid, 'limit': 1,
            'sortDirection': 'desc', 'itemsView': 'notLoaded'})['result']['data'][0]
        active = first.call('thread/read', {'threadId': tid, 'includeTurns': False})['result']['thread']
        assert active['status']['type'] == 'active'
        assert projected['id'] == seed['id'] and projected['status'] == 'interrupted'
        assert projected['completedAt'] is None and projected['items'] == []
        observer.close()
        observer = None
        assert 'result' in first.call('turn/interrupt', {'threadId': tid, 'turnId': seed['id']})
        release.set()
        queued = first.call('thread/queue/add', {'threadId': tid, 'clientUserMessageId': 'cold-queue-exact-once',
            'input': [{'type': 'text', 'text': 'Synthetic protocol fixture. No tool calls.'}]})['result']['queuedSubmission']
        assert first.call('thread/queue/list', {'threadId': tid})['result']['data'][0]['id'] == queued['id']
        first.close()
        first = None
        requests.clear()
        second = Server(tmp_path, 'resume-cold', overrides, local_env)
        resumed = second.call('thread/resume', {'threadId': tid, 'excludeTurns': True})
        assert 'result' in resumed, resumed
        time.sleep(0.2)
        state = second.call('thread/read', {'threadId': tid, 'includeTurns': True})['result']['thread']
        assert state['status']['type'] == 'idle' and not requests, json.dumps({'state': state, 'events': second.events, 'requests': requests})
        assert second.call('thread/queue/list', {'threadId': tid})['result']['data'][0]['id'] == queued['id']
        started = second.call('thread/queue/start', {'threadId': tid, 'queuedSubmissionId': queued['id']})['result']['turn']
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            current = second.call('thread/read', {'threadId': tid, 'includeTurns': True})['result']['thread']
            turn = next((t for t in current['turns'] if t['id'] == started['id']), None)
            completed = [event for event in second.events
                         if event.get('method') == 'turn/completed'
                         and event.get('params', {}).get('threadId') == tid
                         and event.get('params', {}).get('turn', {}).get('id') == started['id']]
            # The installed server may briefly project an active queued turn
            # as interrupted with no completion timestamp. Match the product's
            # confirmedHistoryTerminal boundary instead of treating that
            # historical projection as an actual stop.
            if turn and turn['status'] != 'inProgress' and turn.get('completedAt') is not None and completed:
                break
            time.sleep(0.05)
        assert turn and turn['status'] == 'completed', turn
        assert turn['completedAt'] >= turn['startedAt']
        assert len(completed) == 1 and completed[0]['params']['turn']['status'] == 'completed'
        assert len(requests) == 1
        assert second.call('thread/queue/list', {'threadId': tid})['result']['data'] == []
        repeat = second.call('thread/queue/start', {'threadId': tid, 'queuedSubmissionId': queued['id']})
        assert 'error' in repeat
        assert len(requests) == 1 and list(workspace.iterdir()) == []
        assert sum(e.get('method') == 'turn/started' for e in second.events) == 1
    finally:
        release.set()
        if observer:
            observer.close()
        if second:
            second.close()
        if first:
            first.close()
        http.shutdown()
        http.server_close()
        serving.join(timeout=2)
