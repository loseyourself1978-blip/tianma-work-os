"""Transport coverage, not a substitute for actual Safari layout assertions."""
import io
import json
import urllib.error
import urllib.request

import pytest

from scripts.safari_geometry_bridge import valid_fixture
from tests import test_vol19_fresh_install_first_run_ui as layout


@pytest.mark.parametrize('width', [390,884,1280,1329])
def test_safari_transport_accepts_original_geometry_widths(width):
    assert valid_fixture({'html':'<html></html>','width':width})


@pytest.mark.parametrize('width', [True,None,'1280',1280.0,0,-1,239,4097])
def test_safari_transport_rejects_invalid_or_unbounded_width(width):
    assert not valid_fixture({'html':'<html></html>','width':width})


@pytest.mark.parametrize('kind', ['http_rejection','timeout'])
def test_safari_transport_failure_preserves_input_and_safe_diagnostic(tmp_path,monkeypatch,kind):
    monkeypatch.setenv('TWOS_SAFARI_GEOMETRY_URL','http://127.0.0.1:12345/test/')
    monkeypatch.setenv('PYTEST_CURRENT_TEST','synthetic transport failure control')
    fixture='<html><body>synthetic transport control</body></html>'
    monkeypatch.setattr(layout,'_geometry_fixture',lambda _:fixture)
    calls=[]
    def rejected(request,timeout):
        calls.append(request)
        if kind=='http_rejection':
            raise urllib.error.HTTPError(request.full_url,400,'Bad Request',{},io.BytesIO(b'{"error":"INVALID_FIXTURE","secret":"synthetic-do-not-export"}'))
        raise TimeoutError('synthetic-do-not-export')
    monkeypatch.setattr(urllib.request,'urlopen',rejected)
    with pytest.raises(urllib.error.HTTPError if kind=='http_rejection' else TimeoutError):
        layout._browser_geometry(tmp_path,surface='setup',width=1329)
    assert len(calls)==1
    assert (tmp_path/'safari-setup-1329.html').read_text()==fixture
    raw=(tmp_path/'safari-setup-1329.transport.json').read_text()
    value=json.loads(raw)
    assert value['state']=='FAILED' and value['width']==1329
    assert value['finished_at']>=value['started_at']
    assert 'synthetic-do-not-export' not in raw
    assert not (tmp_path/'safari-setup-1329.json').exists()
    if kind=='http_rejection':
        assert value['http_status']==400 and value['error_code']=='INVALID_FIXTURE'
    else:assert value['exception_type']=='TimeoutError'
