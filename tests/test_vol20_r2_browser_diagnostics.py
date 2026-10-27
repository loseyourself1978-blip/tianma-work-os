"""Fault controls for browser diagnostic capture; no browser/provider launch."""
import errno
import io
import json
import signal
import subprocess
from pathlib import Path

import pytest

from tests import test_vol19_fresh_install_first_run_ui as layout


@pytest.mark.parametrize('case', ['normal', 'kill_denied', 'group_gone', 'drain_timeout', 'launch_denied'])
def test_browser_failure_capture_precedes_propagation(tmp_path, monkeypatch, case):
    geometry = {'innerWidth': 1280, 'measuredAt': 1234, 'overflow': []}
    output = '<pre id="twos-geometry-output">' + json.dumps(geometry) + '</pre>'
    calls = []; signals = []; processes = []

    class Child:
        pid = 123456789  # Synthetic identity; no OS signal is sent.
        returncode = None

        def __init__(self):
            self.stdout = io.BytesIO(); self.stderr = io.BytesIO()

        def communicate(self, timeout):
            calls.append(timeout)
            if case == 'normal':
                self.returncode = 0
                return output, 'synthetic browser diagnostic'
            raise subprocess.TimeoutExpired(['OFFLINE_FIXTURE'], timeout,
                                            output=output.encode(), stderr=b'synthetic partial stderr')

        def poll(self):
            return self.returncode

    def spawn(*args, **kwargs):
        if case == 'launch_denied':
            raise PermissionError(errno.EPERM, 'synthetic launch denied')
        child = Child(); processes.append(child); return child

    def send(pid, signum):
        assert pid == Child.pid
        signals.append(signum)
        if case == 'group_gone':
            raise ProcessLookupError(errno.ESRCH, 'synthetic group gone')
        if case == 'kill_denied' and signum == signal.SIGKILL:
            raise PermissionError(errno.EPERM, 'synthetic signal denied')

    monkeypatch.setattr(layout, '_headless_browser', lambda: Path('/OFFLINE_FIXTURE/browser'))
    monkeypatch.setattr(layout, '_geometry_fixture', lambda surface: '<html>fixture</html>')
    monkeypatch.setattr(layout.subprocess, 'Popen', spawn)
    monkeypatch.setattr(layout.os, 'killpg', send)
    if case == 'normal':
        assert layout._browser_geometry(tmp_path, surface='fixture', width=1280) == geometry
    else:
        error = subprocess.TimeoutExpired if case == 'drain_timeout' else ProcessLookupError if case == 'group_gone' else PermissionError
        with pytest.raises(error):
            layout._browser_geometry(tmp_path, surface='fixture', width=1280)
    diagnostic = tmp_path / 'geometry-fixture-1280'
    receipt = json.loads((diagnostic / 'receipt.json').read_text())
    assert receipt['output_complete'] is (case == 'normal')
    assert receipt['return_code'] == (0 if case == 'normal' else 'UNKNOWN')
    assert receipt['marker_found'] is (case != 'launch_denied')
    assert receipt['phase'] == ('PARENT_MARKER_RECEIVED' if case == 'normal' else 'PROCESS_ERROR')
    assert (diagnostic / 'stdout.html').read_text() == ('' if case == 'launch_denied' else output)
    assert receipt['process_error'] == (None if case == 'normal' else {
        'type': 'TimeoutExpired' if case == 'drain_timeout' else 'ProcessLookupError' if case == 'group_gone' else 'PermissionError',
        'errno': None if case == 'drain_timeout' else errno.ESRCH if case == 'group_gone' else errno.EPERM,
    })
    assert calls == ([] if case == 'launch_denied' else [10] if case in ('normal', 'group_gone') else [10, 5, 5] if case == 'drain_timeout' else [10, 5])
    assert signals == ([] if case in ('normal', 'launch_denied') else [signal.SIGTERM] if case == 'group_gone' else [signal.SIGTERM, signal.SIGKILL])
    assert all(child.stdout.closed and child.stderr.closed for child in processes)
