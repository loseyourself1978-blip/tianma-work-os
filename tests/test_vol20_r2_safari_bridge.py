"""Transport coverage, not a substitute for actual Safari layout assertions."""
import io
import json
import hashlib
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from scripts.safari_geometry_bridge import browser_ready, valid_fixture
from tests import test_vol19_fresh_install_first_run_ui as layout


@pytest.mark.parametrize('width', [390,884,1280,1329])
def test_safari_transport_accepts_original_geometry_widths(width):
    assert valid_fixture({'html':'<html></html>','width':width})


@pytest.mark.parametrize('width', [True,None,'1280',1280.0,0,-1,239,4097])
def test_safari_transport_rejects_invalid_or_unbounded_width(width):
    assert not valid_fixture({'html':'<html></html>','width':width})


@pytest.mark.parametrize('visibility,age,user_agent,expected', [
    ('visible',0,'Version/27 Safari/625.1',True),
    ('visible',3,'Version/27 Safari/625.1',True),
    ('hidden',0,'Version/27 Safari/625.1',False),
    ('visible',3.01,'Version/27 Safari/625.1',False),
    ('visible',-1,'Version/27 Safari/625.1',False),
    ('visible',0,'Chrome/140 Safari/537.36',False),
    ('visible',0,'unknown',False),
])
def test_only_fresh_visible_actual_safari_can_receive_geometry_fixture(visibility,age,user_agent,expected):
    assert not browser_ready(None,100)
    receipt={'visibility':visibility,'received_at':100-age,'userAgent':user_agent}
    assert browser_ready(receipt,100) is expected


@pytest.mark.parametrize('kind', ['http_rejection','timeout','visibility_race'])
def test_safari_transport_failure_preserves_input_and_safe_diagnostic(tmp_path,monkeypatch,kind):
    monkeypatch.setenv('TWOS_SAFARI_GEOMETRY_URL','http://127.0.0.1:12345/test/')
    monkeypatch.setenv('PYTEST_CURRENT_TEST','synthetic transport failure control')
    fixture='<html><body>synthetic transport control</body></html>'
    monkeypatch.setattr(layout,'_geometry_fixture',lambda _:fixture)
    calls=[]
    def rejected(request,timeout):
        if isinstance(request,str) and request.endswith('/status'):
            return io.BytesIO(json.dumps({'ready':True,'browser':{
                'visibility':'visible','received_at':layout.time.time(),
                'userAgent':'Version/27 Safari/625.1'}}).encode())
        calls.append(request)
        if kind=='http_rejection':
            raise urllib.error.HTTPError(request.full_url,400,'Bad Request',{},io.BytesIO(b'{"error":"INVALID_FIXTURE","secret":"synthetic-do-not-export"}'))
        if kind=='visibility_race':
            raise urllib.error.HTTPError(request.full_url,409,'Conflict',{},io.BytesIO(b'{"error":"SAFARI_NOT_VISIBLE_OR_STALE"}'))
        raise TimeoutError('synthetic-do-not-export')
    monkeypatch.setattr(urllib.request,'urlopen',rejected)
    with pytest.raises(TimeoutError if kind=='timeout' else urllib.error.HTTPError):
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
    elif kind=='visibility_race':
        assert value['http_status']==409 and value['error_code']=='SAFARI_NOT_VISIBLE_OR_STALE'
    else:assert value['exception_type']=='TimeoutError'


@pytest.mark.parametrize('becomes_ready',[True,False])
def test_each_safari_fixture_waits_before_submission_without_replaying(tmp_path,monkeypatch,becomes_ready):
    monkeypatch.setenv('TWOS_SAFARI_GEOMETRY_URL','http://127.0.0.1:12345/test/')
    fixture='<html><body>TEST readiness control</body></html>'
    monkeypatch.setattr(layout,'_geometry_fixture',lambda _:fixture)
    clock=[0.0];calls=[];reads=[0]
    monkeypatch.setattr(layout,'time',SimpleNamespace(time=lambda:100+clock[0],monotonic=lambda:clock[0],sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)))
    def respond(request,timeout):
        if isinstance(request,str):
            assert request.endswith('/status');reads[0]+=1
            ready=becomes_ready and reads[0]>2
            return io.BytesIO(json.dumps({'ready':ready,'browser':{
                'visibility':'visible' if ready else 'hidden','received_at':100+clock[0],
                'userAgent':'Version/27 Safari/625.1'}}).encode())
        calls.append(request)
        assert reads[0]>=3 and clock[0]>=2
        return io.BytesIO(json.dumps({'id':'TEST-receipt','fixture_sha256':hashlib.sha256(fixture.encode()).hexdigest(),
            'width':390,'method':'ACTUAL_SAFARI_NATIVE_TAB_FIXED_WIDTH_IFRAME','geometry':{'innerWidth':390}}).encode())
    monkeypatch.setattr(urllib.request,'urlopen',respond)
    if becomes_ready:
        assert layout._browser_geometry(tmp_path,surface='setup',width=390)=={'innerWidth':390}
        assert len(calls)==1
    else:
        with pytest.raises(RuntimeError,match='SAFARI_NOT_READY_BEFORE_MEASUREMENT'):
            layout._browser_geometry(tmp_path,surface='setup',width=390)
        assert not calls and clock[0]==60
        assert json.loads((tmp_path/'safari-setup-390.transport.json').read_text())['state']=='FAILED'
