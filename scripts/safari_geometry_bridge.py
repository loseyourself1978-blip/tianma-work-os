#!/usr/bin/env python3
"""Local test fixture bridge, opened normally in actual Safari (no WebDriver).

The existing geometry assertions are unchanged. The test sends its exact
fixture; Safari measures it in the same fixed-width iframe used by Chrome.
This server is test-only, loopback-only, serial, and never calls a provider.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
import uuid


PAGE = '''<!doctype html><meta charset="utf-8"><title>TWOS Safari geometry validation</title>
<h1>Actual Safari · isolated geometry fixtures</h1><pre id="status">Waiting for a test</pre>
<script>
let current=null, frame=null, deadline=null, completion=null, clientStarted=null, checkpoints=[];
const status=document.querySelector('#status');
const browserState=()=>({at:Date.now(),visibility:document.visibilityState,focused:document.hasFocus()});
async function finish(payload){
 if(!current)return;
 const id=current.id;current=null;clearTimeout(deadline);
 try{await fetch('result',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,userAgent:navigator.userAgent,clientStarted,clientFinished:browserState(),checkpoints,...payload})});
 status.textContent=JSON.stringify({id,...payload},null,2);}
 finally{completion?.();}
}
window.addEventListener('message',e=>{
 if(current&&frame&&e.source===frame.contentWindow&&typeof e.data?.twosCheckpoint==='string'&&checkpoints.length<100)checkpoints.push({phase:e.data.twosCheckpoint.slice(0,240),at:Date.now()});
 if(current&&frame&&e.source===frame.contentWindow&&e.data?.twosGeometry)finish({geometry:e.data.twosGeometry});
});
async function poll(){
 while(true){try{const response=await fetch('next',{cache:'no-store'});const item=await response.json();
 if(item){current=item;checkpoints=[];clientStarted=browserState();const done=new Promise(resolve=>completion=resolve);
 if(frame)frame.remove();frame=document.createElement('iframe');
 frame.style=`display:block;border:0;width:${item.width}px;height:20000px`;
 frame.srcdoc=item.html;status.textContent='Measuring '+item.id;
 deadline=setTimeout(()=>finish({error:'SAFARI_MEASUREMENT_TIMEOUT'}),10000);document.body.appendChild(frame);await done;}}
 catch(e){status.textContent='Bridge error: '+e.name;await new Promise(resolve=>setTimeout(resolve,1000));}}
}poll();
</script>'''


def valid_fixture(body):
    # Original geometry cases include 884 and 1329, not only 390/1280.
    # Bound the transport size without narrowing the test's viewport contract.
    width=body.get('width')
    return type(body.get('html')) is str and type(width) is int and 240 <= width <= 4096


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True)
    args=parser.parse_args();args.evidence.mkdir(parents=True,exist_ok=False,mode=0o700)
    lock=threading.Lock();state={'job':None,'result':None,'served':False,'event':threading.Event(),
                                'available':threading.Event(),'served_at':None,'received_at':None}
    token=uuid.uuid4().hex
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,value,status=200,html=False):
            raw=value.encode() if html else json.dumps(value).encode()
            self.send_response(status);self.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json')
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def route(self):return self.path.removeprefix('/'+token+'/') if self.path.startswith('/'+token+'/') else None
        def do_GET(self):
            route=self.route()
            if route=='':return self.send(PAGE,html=True)
            if route=='next':
                # Wait for a job instead of relying on background-tab timer polling.
                # The measurement deadline remains ten seconds; no retries are added.
                state['available'].wait(5)
                with lock:
                    job=state['job'] if not state['served'] else None
                    if job:
                        state.update(served=True,served_at=time.time());state['available'].clear()
                return self.send(job)
            self.send({'error':'NOT_FOUND'},404)
        def do_POST(self):
            route=self.route();length=int(self.headers.get('Content-Length','0'))
            if route not in ('measure','result') or not 0<length<=2_000_000:return self.send({'error':'INVALID_REQUEST'},400)
            try:body=json.loads(self.rfile.read(length))
            except ValueError:return self.send({'error':'INVALID_JSON'},400)
            if route=='result':
                with lock:
                    job=state['job']
                    if not job or body.get('id')!=job['id'] or state['result'] is not None:return self.send({'error':'STALE_RESULT'},409)
                    ua=body.get('userAgent','')
                    if 'Safari/' not in ua or any(x in ua for x in ('Chrome/','Chromium/','Edg/')):body={'id':job['id'],'error':'NOT_SAFARI','userAgent':ua}
                    state.update(result=body,received_at=time.time());state['event'].set()
                return self.send({'recorded':True})
            with lock:
                if state['job']:return self.send({'error':'BUSY'},409)
                if not valid_fixture(body):return self.send({'error':'INVALID_FIXTURE'},400)
                job={**body,'id':uuid.uuid4().hex};state.update(job=job,result=None,served=False,served_at=None,received_at=None)
                state['event'].clear();state['available'].set()
            started=time.time();state['event'].wait(12)
            with lock:
                result=state['result'] or {'id':job['id'],'error':'SAFARI_NOT_CONNECTED_OR_TIMEOUT'}
                receipt={**result,'fixture_sha256':hashlib.sha256(job['html'].encode()).hexdigest(),'width':job['width'],
                         'surface':job['surface'],'test':job.get('test'),'started_at':started,'finished_at':time.time(),
                         'served_at':state['served_at'],'received_at':state['received_at'],
                         'method':'ACTUAL_SAFARI_NATIVE_TAB_FIXED_WIDTH_IFRAME','browser_spawned_by_test':False}
                (args.evidence/(job['id']+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')
                (args.evidence/(job['id']+'.html')).write_text(job['html'])
                state.update(job=None,result=None,served=False);state['available'].clear()
            self.send(receipt)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    url=f'http://127.0.0.1:{server.server_port}/{token}/'
    (args.evidence/'bridge.json').write_text(json.dumps({'url':url,'method':'native Safari tab; no Chrome surrogate'},indent=2)+'\n')
    print(url,flush=True);server.serve_forever()


if __name__=='__main__':main()
