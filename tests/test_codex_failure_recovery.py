"""Additional recovery gate: actual failed connection, then explicit retry.

Compiles the same production transport as the complete matched gate. Fixture
processes do not use a provider account or create a model turn.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOURCE / 'tests'))
from test_codex_connection_lifecycle import HARNESS, SERVER

pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='macOS AppKit')


@pytest.fixture(scope='module')
def compiled_recovery(tmp_path_factory):
    path = tmp_path_factory.mktemp('codex-failed-recovery')
    harness = HARNESS.replace(
        'client.connectionProcessFactory = factory(mode)',
        'client.connectionProcessFactory = factory(mode == "auth_retry" ? "auth" : "no_handshake")',
    ).replace(
        '["missing","auth","no_handshake","malformed","oversized","exit","eof","timeout"].contains(mode)',
        '["auth_retry","handshake_retry"].contains(mode)',
    ).replace(
        'precondition(!client.connected && !client.connectionError.isEmpty)',
        '''precondition(!client.connected && !client.connectionError.isEmpty)
 let firstGeneration = client.transportGeneration
 precondition(client.process == nil && client.callbacks.isEmpty)
 client.connectionProcessFactory = factory("success")
 client.connect()
 spin(5){client.connected && !client.connecting}
 precondition(client.transportGeneration != firstGeneration)
 precondition(client.connectionError.isEmpty && client.modelCatalog.count == 1 && client.threadRows.count == 1)
''',
    )
    source = (SOURCE / 'packaging/macos/TianmaLauncher.swift').read_text().split('// The only child runtime', 1)[0]
    source += '\n' + '\n'.join((SOURCE / 'packaging/macos' / name).read_text() for name in ('CodexAttachments.swift', 'CodexTelemetry.swift', 'NativeCodex.swift'))
    (path / 'main.swift').write_text(source + harness)
    (path / 'server.py').write_text(SERVER)
    result = subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-O', '-module-cache-path', str(path / 'cache'), str(path / 'main.swift'), '-o', str(path / 'client')], capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    return path


@pytest.mark.parametrize('mode', ['auth_retry', 'handshake_retry'])
def test_failed_connection_can_retry_without_blocking_or_replay(compiled_recovery, tmp_path, mode):
    result = subprocess.run([str(compiled_recovery / 'client'), str(tmp_path), mode, sys.executable, str(compiled_recovery / 'server.py'), str(SOURCE / 'static_cockpit')], capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stderr
    assert f'CONNECTION_PASS {mode}' in result.stdout
    calls = [json.loads(line) for line in (tmp_path / 'methods.jsonl').read_text().splitlines()]
    assert not any(row['method'] in ['turn/start', 'thread/start', 'thread/resume', 'thread/queue/add', 'account/login/start'] for row in calls)
    assert len({row['pid'] for row in calls}) == (2 if mode == 'auth_retry' else 1)
    for pid in {row['pid'] for row in calls}:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    print(result.stdout.strip())
