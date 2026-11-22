"""Exercise a restored 1.0.13 queue and its actual AppKit/WebKit controls."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/team_connection'


@pytest.mark.skipif(sys.platform != 'darwin', reason='native WebKit member window')
def test_signed_out_member_can_resume_first_message_once(tmp_path):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    with ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=FIXTURE)) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            mac = ROOT / 'packaging/macos'
            launcher = (mac / 'TianmaLauncher.swift').read_text().split('// The only child runtime', 1)[0]
            parts = [launcher]
            for name in ('CodexAttachments','CodexTelemetry','NativeCodex','TeamReport','TeamRun',
                         'TeamConversation','TeamArtifacts','TeamWorkspace','TeamChatWorkspace',
                         'IntegratedWorkbench','PairedWorkflow'):
                source = (mac / (name + '.swift')).read_text()
                if name == 'TeamRun':
                    original = '"ChatGPT": "https://chatgpt.com/"'
                    assert source.count(original) == 1
                    source = source.replace(original, f'"ChatGPT": "http://127.0.0.1:{server.server_port}/"')
                parts.append(source)
            parts.append((FIXTURE / 'probe.swift').read_text())
            main = tmp_path / 'main.swift'
            main.write_text('\n'.join(parts))
            binary = tmp_path / 'connection-test'
            subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',
                            str(tmp_path/'cache'),str(main),'-o',str(binary)],check=True,timeout=180)
            for case in ('resume', 'stop', 'uncertain', 'retained', 'manual', 'missing', 'richText', 'prepareError',
                         'timeoutBoundary', 'delayedRoute'):
                result = subprocess.run([str(binary),str(tmp_path/case),str(ROOT/'static_cockpit'),case],
                                        env=os.environ,capture_output=True,text=True,timeout=75)
                assert result.returncode == 0, case + ': ' + result.stdout + result.stderr
                print(result.stdout.strip())
        finally:
            server.shutdown()
            thread.join()
