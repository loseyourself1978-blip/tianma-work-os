"""Transport coverage, not a substitute for actual Safari layout assertions."""
import io
import json
import hashlib
from types import SimpleNamespace
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import time
import uuid

import pytest

from scripts.safari_geometry_bridge import browser_ready, valid_fixture, selected_browser, matching_browser
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


@pytest.mark.parametrize('other_kind', ['chrome','hidden_safari','stale_safari'])
def test_browser_readiness_is_per_client_not_the_last_browser_heartbeat(other_kind):
    safari={'clientID':'safari','visibility':'visible','focused':True,'received_at':99,
            'userAgent':'Version/27 Safari/625.1'}
    other={**safari,'clientID':'other','received_at':100}
    if other_kind=='chrome':other['userAgent']='Chrome/156 Safari/537.36'
    elif other_kind=='hidden_safari':other['visibility']='hidden'
    else:other['received_at']=95
    browsers={'safari':safari,'other':other}
    assert selected_browser(browsers,100)==safari
    assert matching_browser(browsers,'safari',safari['userAgent'],100)
    assert not matching_browser(browsers,'other',other['userAgent'],100)
    assert not matching_browser(browsers,'safari',other['userAgent']+' changed',100)


def test_http_measurement_cannot_be_claimed_or_finished_by_another_browser(tmp_path):
    """SIMULATED HTTP clients exercise the transport race; not actual Safari proof."""
    root=Path(__file__).resolve().parents[1]
    evidence=tmp_path/'bridge'
    with (tmp_path/'bridge.log').open('w') as log:
        process=subprocess.Popen([sys.executable,str(root/'scripts/safari_geometry_bridge.py'),
                                  '--evidence',str(evidence)],stdout=log,stderr=log)
        try:
            deadline=time.monotonic()+10
            while not (evidence/'bridge.json').exists():
                assert process.poll() is None
                assert time.monotonic()<deadline
                time.sleep(.02)
            url=json.loads((evidence/'bridge.json').read_text())['url']
            safari=str(uuid.uuid4());chrome=str(uuid.uuid4());other=str(uuid.uuid4())
            safari_ua='Version/27 Safari/625.1';chrome_ua='Chrome/156 Safari/537.36'
            def request(route,body=None,client=None,ua='TEST controller'):
                headers={'User-Agent':ua}
                if client:headers['X-TWOS-Browser']=client
                if body is not None:headers['Content-Type']='application/json'
                req=urllib.request.Request(url+route,data=None if body is None else json.dumps(body).encode(),headers=headers)
                try:
                    with urllib.request.urlopen(req,timeout=15) as response:return response.status,json.load(response)
                except urllib.error.HTTPError as error:return error.code,json.load(error)
            def ready(client,ua,visible=True):
                return request('ready',{'clientID':client,'userAgent':ua,'visibility':'visible' if visible else 'hidden',
                    'focused':visible,'at':time.time()*1000},client,ua)
            assert ready(safari,safari_ua)[1]['ready']
            assert not ready(chrome,chrome_ua)[1]['ready']
            assert not ready(other,safari_ua,False)[1]['ready']
            assert request('status')[1]['browser']['clientID']==safari
            assert request('next',client=chrome,ua=chrome_ua)[0]==409
            fixture={'html':'<p>TEST ONLY browser ownership</p>','width':390,'surface':'fixture'}
            with ThreadPoolExecutor(max_workers=1) as pool:
                measurement=pool.submit(request,'measure',fixture)
                status,job=request('next',client=safari,ua=safari_ua)
                assert status==200 and job['clientID']==safari
                assert ready(other,safari_ua)[1]['ready']
                payload={'id':job['id'],'clientID':other,'userAgent':safari_ua,'geometry':{'innerWidth':999}}
                assert request('result',payload,other,safari_ua)==(409,{'error':'WRONG_BROWSER_RESULT'})
                payload.update(clientID=safari,geometry={'innerWidth':390})
                assert request('result',payload,safari,safari_ua)==(200,{'recorded':True})
                status,receipt=measurement.result(timeout=15)
            assert status==200 and not receipt.get('error')
            assert receipt['geometry']=={'innerWidth':390} and receipt['clientID']==safari
            assert request('result',payload,safari,safari_ua)[0]==409
            assert len(list(evidence.glob('*.html')))==1
        finally:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)
