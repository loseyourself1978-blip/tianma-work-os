"""Real local socket framing/deadlines with a TEST ONLY peer-policy fixture.

This validates the production transport, not a substitute for signed peers or
Owner mouse/IME verification. No model, browser profile or business data is used.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='macOS peer transport')

@pytest.fixture(scope='module')
def control_binary(tmp_path_factory):
    temp = tmp_path_factory.mktemp('nyra-user-control-compile')
    source = (ROOT/'packaging/macos/IntegratedWorkbench.swift').read_text()
    transport = source.split('final class NyraControlServer {', 1)[1].split('// User actions are bound', 1)[0]
    harness = r'''
import Foundation
import Darwin
final class NyraControlServer {
''' + transport + r'''
let root=URL(fileURLWithPath:CommandLine.arguments[1]),instance=CommandLine.arguments[2]
let readonly=CommandLine.arguments[3]=="readonly"
let focusOnly=CommandLine.arguments[3]=="focusOnly"
var mutations=0,ticks=0
let server=try NyraControlServer(root:root,instance:instance,focusOnly:focusOnly,authenticate:{pid,uid,method in
    pid>0 && uid==geteuid() && (!readonly || ["focus","inspect"].contains(method))
},handle:{request,reply in
    let method=request["method"] as! String
    if ["submit","stop","editQueue"].contains(method){mutations+=1}
    reply(["state":"TEST_ONLY","mutations":mutations,"ticks":ticks,"userControls":request["_userControls"] as? Bool ?? false])
})
let timer=Timer.scheduledTimer(withTimeInterval:0.01,repeats:true){_ in ticks+=1}
let started:[String:Any]=["uptime":ProcessInfo.processInfo.systemUptime,"path":server.path]
print(String(data:try JSONSerialization.data(withJSONObject:started),encoding:.utf8)!);fflush(stdout)
RunLoop.main.run(until:Date(timeIntervalSinceNow:15))
server.stop()
'''
    swift=temp/'main.swift';swift.write_text(harness);binary=temp/'control-test'
    result=subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(temp/'cache'),str(swift),'-o',str(binary)],capture_output=True,text=True,timeout=90)
    assert result.returncode==0,result.stderr
    return binary

@pytest.mark.parametrize('policy',['authorized','readonly'])
def test_bounded_control_socket_identity_replay_and_cleanup(control_binary,policy):
    root=Path(tempfile.mkdtemp(prefix='twos-control-fixture-',dir='/private/tmp'))
    host=str(uuid.uuid4());consumer=str(uuid.uuid4())
    process=subprocess.Popen([str(control_binary),str(root),host,policy],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    clients=[]
    try:
        start=json.loads(process.stdout.readline());clock=time.monotonic()
        def request(method='inspect',**extra):
            return dict(protocol='twos.nyra.control.v1',hostInstance=host,consumerInstance=consumer,requestID=str(uuid.uuid4()),method=method,issuedUptime=start['uptime']+time.monotonic()-clock,**extra)
        def connect():
            client=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);client.settimeout(5);client.connect(start['path']);clients.append(client);return client
        def exchange(value):
            client=connect();client.sendall(json.dumps(value).encode()+b'\n');data=b''
            while b'\n' not in data:
                part=client.recv(8192)
                if not part:break
                data+=part
            client.close();clients.remove(client)
            return json.loads(data) if data else None
        first=exchange(request());assert first['hostInstance']==host and first['userControls']==(policy=='authorized')
        wrong=request();wrong['hostInstance']=str(uuid.uuid4());assert 'error' in exchange(wrong)
        stale=request();stale['issuedUptime']-=20;assert 'error' in exchange(stale)
        injected=request('run-shell');assert 'error' in exchange(injected)
        mutation=request('submit',text='TEST ONLY no execution');one=exchange(mutation);two=exchange(mutation)
        if policy=='authorized':
            assert one==two and one['mutations']==1
            assert exchange(request())['mutations']==1
        else:assert 'error' in one and exchange(request())['mutations']==0
        # A partial line cannot hold the main loop or other socket clients.
        slow=connect();slow.sendall(b'{');time.sleep(.08)
        responsive=exchange(request());assert responsive['ticks']>first['ticks']
        # Malformed framing never reaches the action handler.
        bad=connect();bad.sendall(b'not json\n');assert bad.recv(20)==b'';bad.close();clients.remove(bad)
        big=connect()
        try:big.sendall(b'x'*240001+b'\n')
        except (BrokenPipeError,ConnectionResetError):pass
        try:assert big.recv(20)==b''
        except ConnectionResetError:pass
        big.close();clients.remove(big)
        # The production deadline closes the unfinished request.
        assert slow.recv(20)==b'';slow.close();clients.remove(slow)
        last=exchange(request());assert last['mutations']==(1 if policy=='authorized' else 0)
    finally:
        for client in clients:client.close()
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        shutil.rmtree(root)


def test_host_focus_is_independent_and_cannot_mutate_or_select_tasks(control_binary):
    root = Path(tempfile.mkdtemp(prefix='twos-focus-fixture-', dir='/private/tmp'))
    host, consumer = str(uuid.uuid4()), str(uuid.uuid4())
    process = subprocess.Popen([str(control_binary), str(root), host, 'focusOnly'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        start = json.loads(process.stdout.readline())
        clock = time.monotonic()
        assert Path(start['path']).name == 'focus.sock'
        assert not (root / 'control.sock').exists()
        def exchange(**changes):
            payload = dict(protocol='twos.nyra.focus.v1', hostInstance=host, consumerInstance=consumer,
                           requestID=str(uuid.uuid4()), method='focus', issuedUptime=start['uptime']+time.monotonic()-clock)
            payload.update(changes)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(5)
                client.connect(start['path'])
                client.sendall(json.dumps(payload).encode()+b'\n')
                data = b''
                while b'\n' not in data:
                    part = client.recv(8192)
                    if not part:
                        break
                    data += part
            return json.loads(data)
        focused = exchange()
        assert focused['state'] == 'TEST_ONLY' and focused['userControls'] is False
        for fields in [dict(method='submit'), dict(method='stop'), dict(method='draft'),
                       dict(target='a'*64), dict(text='TEST ONLY'), dict(revision='draft'),
                       dict(hostInstance=str(uuid.uuid4())), dict(protocol='twos.nyra.control.v1')]:
            assert 'error' in exchange(**fields)
        assert exchange()['mutations'] == 0
    finally:
        process.terminate()
        process.wait(timeout=5)
        shutil.rmtree(root)
