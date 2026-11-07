"""Compiled production client with owned fault-process fixtures; no model requests.

REAL_GUI / official protocol validation is recorded separately. A live AppKit
main-run-loop heartbeat must continue in every case, including backpressure.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='macOS native connection')
SERVER = r'''
import sys,json,time,os,threading
mode,log=sys.argv[1:3]
def send(v):
 data=(json.dumps(v)+'\n').encode()
 if mode=='fragmented':
  for i in range(0,len(data),997):os.write(1,data[i:i+997])
 else:os.write(1,data)
if mode=='slow':time.sleep(.2)
if mode=='no_handshake':time.sleep(10);sys.exit()
if mode=='oversized':os.write(1,(json.dumps({'result':'x'*24_000_001})+'\n').encode());time.sleep(10);sys.exit()
if mode=='malformed':os.write(1,b'not json\n');time.sleep(10);sys.exit()
if mode=='eof':os.close(1);time.sleep(10);sys.exit()
if mode=='stderr':
 def flood():
  while True:
   try:os.write(2,b'TEST ONLY stderr backpressure\n'*2048);time.sleep(.001)
   except OSError:return
 threading.Thread(target=flood,daemon=True).start()
for line in sys.stdin:
 v=json.loads(line);m=v.get('method');i=v.get('id')
 with open(log,'a') as f:f.write(json.dumps({'pid':os.getpid(),'method':m,'params':v.get('params',{})})+'\n')
 if m=='initialize':
  send({'id':999999,'result':{'unmatched':True}})
  send({'id':i,'result':{'userAgent':'fixture'}})
 elif m=='account/read':
  if mode=='exit':sys.exit(7)
  send({'id':i,'result':{'requiresOpenaiAuth':True,'account':None if mode=='auth' else {'type':'chatgpt'}}})
 elif m=='model/list':send({'id':i,'result':{'data':[{'model':'fixture','inputModalities':['text']}]}})
 elif m=='thread/list':
  preview='TEST ONLY '+('x'*4_000_000 if mode=='fragmented' else '')
  send({'id':i,'result':{'data':[{'id':'00000000-0000-4000-8000-000000000001','cwd':'/synthetic','preview':preview}]}})
 elif m=='thread/read':send({'id':i,'result':{'thread':{'id':v['params']['threadId'],'cwd':'/synthetic'}}})
 elif m=='thread/turns/list':
  p=v['params'];view=p.get('itemsView')
  if view=='full':send({'id':i,'result':{'data':[{'id':'large','items':[{'type':'commandExecution','aggregatedOutput':'x'*25_000_000}]}]}})
  elif mode=='history_read_error':send({'id':i,'error':{'code':-32602,'message':'TEST ONLY summary unavailable'}})
  else:
   items=[] if view=='notLoaded' else [{'id':'u1','type':'userMessage','clientId':'exact-input-id','content':[{'type':'text','text':'TEST ONLY'}]},{'id':'a1','type':'agentMessage','phase':'final_answer','text':'TEST ONLY complete'}]
   send({'id':i,'result':{'data':[{'id':'older' if p.get('cursor') else 'latest','status':'completed','startedAt':1,'completedAt':2,'itemsView':view,'items':items}],'nextCursor':None if p.get('cursor') else 'older-page'}})
 elif m=='thread/items/list':
  if mode=='history_activity_error':send({'id':i,'error':{'code':-32601,'message':'TEST ONLY unsupported'}})
  else:send({'id':i,'result':{'data':[{'turnId':'latest','item':{'id':'tool1','type':'commandExecution','command':'TEST ONLY','aggregatedOutput':'safe output'}}],'nextCursor':None if v['params'].get('cursor') else 'items-next'}})
 elif m=='block_stdin':time.sleep(10)
 elif m=='hung':pass
 elif i is not None:send({'id':i,'result':{}})
'''
HARNESS = r'''
let application = NSApplication.shared
let root = URL(fileURLWithPath:CommandLine.arguments[1])
let mode = CommandLine.arguments[2]
let python = CommandLine.arguments[3], server = CommandLine.arguments[4]
let resources = URL(fileURLWithPath:CommandLine.arguments[5])
try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
let client = NativeCodex(resources:resources,preferences:root.appendingPathComponent("prefs"),translate:{$0})
client.connectionTimeout = 1.5;client.requestTimeout = 0.7
var ticks=0, maximumGap=0.0, last=ProcessInfo.processInfo.systemUptime, launches=0
let heartbeat=Timer(timeInterval:0.005,repeats:true) { _ in
 let now=ProcessInfo.processInfo.systemUptime; maximumGap=max(maximumGap,now-last);last=now;ticks+=1
}
RunLoop.main.add(heartbeat,forMode:.common)
func spin(_ timeout:Double,_ done:()->Bool) {
 let end=ProcessInfo.processInfo.systemUptime+timeout
 while !done() && ProcessInfo.processInfo.systemUptime<end {RunLoop.current.run(until:Date(timeIntervalSinceNow:0.005))}
 precondition(done(),"deadline \(mode); phase=\(client.connectionPhase), error=\(client.connectionError)")
}
func factory(_ kind:String)->()->Process { return {
 let p=Process();p.executableURL=URL(fileURLWithPath:python);p.arguments=[server,kind,root.appendingPathComponent("methods.jsonl").path];return p
}}
client.connectionProcessFactory = factory(mode)
if mode=="missing" {client.connectionProcessFactory={let p=Process();p.executableURL=URL(fileURLWithPath:"/nonexistent/twos-codex-fixture");return p}}
if mode=="slow_factory" {client.connectionProcessFactory={Thread.sleep(forTimeInterval:0.2);return factory("success")()}}
if mode=="cancel_launch" {client.connectionProcessFactory={Thread.sleep(forTimeInterval:0.35);return factory("success")()}}
let savedID="00000000-0000-4000-8000-000000000001"
if mode.hasPrefix("history_") {client.restoringThread=savedID}
let begin=ProcessInfo.processInfo.systemUptime
client.connect();precondition(ProcessInfo.processInfo.systemUptime-begin<0.15,"connect must return immediately")
let first=client.transport
if ["double","cancel","cancel_launch","stale","retry","backpressure","request_timeout"].contains(mode) {client.connect();precondition(client.transport === first)}
if ["cancel","cancel_launch","stale","retry"].contains(mode) {
 let oldMessage=first?.onMessage,oldLaunch=first?.onLaunch
 client.disconnect();client.connect();precondition(client.transport == nil,"never overlap a cancelled child that has not exited")
 spin(6){client.closingTransport == nil}
 precondition(!client.connected && !client.connecting)
 if mode=="stale" {
  oldMessage?(["method":"turn/started","params":["threadId":"stale","turn":["id":"stale"]]])
  let p=Process();oldLaunch?(p);precondition(client.process == nil && client.turnID == nil)
 }
 if mode=="retry" {client.connectionProcessFactory=factory("success");client.connect();spin(5){client.connected && !client.connecting};precondition(client.modelCatalog.count==1)}
} else if ["missing","auth","no_handshake","malformed","oversized","exit","eof","timeout"].contains(mode) {
 if mode=="timeout" {client.disconnect();spin(6){client.closingTransport == nil};client.connectionProcessFactory=factory("no_handshake");client.connectionTimeout=0.25;client.connect()}
 spin(7){!client.connecting && client.closingTransport == nil && client.transport == nil}
 precondition(!client.connected && !client.connectionError.isEmpty)
 if mode=="malformed" {precondition(client.connectionError=="invalid_jsonl")}
 if mode=="oversized" {precondition(client.connectionError=="jsonl_frame_too_large")}
} else {
 spin(8){client.connected && !client.connecting}
 precondition(client.modelCatalog.count==1 && client.threadRows.count==1 && client.callbacks.keys.allSatisfy{$0 != 999999})
 if mode.hasPrefix("history_") {
  spin(5){client.threadID==savedID && !client.historyLoading}
  if mode=="history_read_error" {
   precondition(!client.historyReady && client.connected && !client.isBusy)
  } else {
   precondition(client.historyReady && client.lastHistoryTurn=="latest")
   client.loadHistory(older:true);spin(3){!client.historyLoading};precondition(client.historyCursor==nil)
   client.refreshRunObservation();spin(3){!client.runReading}
   client.loadHistoryActivity(older:false)
   let count=client.requestID;client.loadHistoryActivity(older:false);precondition(client.requestID==count,"deduplicate item reads")
   spin(3){!client.historyActivityLoading}
   if mode=="history_activity_error" {precondition(client.connected && client.historyReady && client.historyActivityCursor==nil)}
   else {
    precondition(client.historyActivityCursor=="items-next")
    client.loadHistoryActivity(older:true);spin(3){!client.historyActivityLoading};precondition(client.historyActivityCursor==nil)
   }
   // Delayed callbacks from the old selection must not overwrite a new page.
   client.loadHistoryActivity(older:false)
   let stale=client.callbacks[client.requestID]
   client.selectionGeneration += 1;client.historyActivityLoading=false;client.historyActivityCursor="new-selection"
   stale?(["data":[],"nextCursor":"wrong"]);precondition(client.historyActivityCursor=="new-selection")
   if mode=="history_reconnect" {
    client.disconnect();spin(6){client.closingTransport==nil};client.connect()
    spin(6){client.connected && client.historyReady && !client.connecting}
   }
  }
 }
 if mode=="backpressure" {
  client.write(["method":"block_stdin"])
  for _ in 0..<4 {client.write(["method":"fixture","params":["text":String(repeating:"x",count:1_000_000)]])}
  let startTicks=ticks;spin(0.3){ticks-startTicks>15}
 }
 if mode=="request_timeout" {var ended=false;client.request("hung",[:]){r in precondition(r==nil);ended=true};spin(2){ended}}
}
client.disconnect();spin(6){client.closingTransport == nil}
precondition(client.process == nil && client.callbacks.isEmpty && client.turnID == nil)
precondition(ticks>=2 && maximumGap<0.35,"main run loop stalled: \(maximumGap)")
print("CONNECTION_PASS \(mode) ticks=\(ticks) max_gap=\(maximumGap)")
exit(0)
'''

@pytest.fixture(scope='module')
def compiled(tmp_path_factory):
    path=tmp_path_factory.mktemp('codex-connection')
    source=(ROOT/'packaging/macos/TianmaLauncher.swift').read_text().split('// The only child runtime',1)[0]
    source+='\n'+'\n'.join((ROOT/'packaging/macos'/n).read_text() for n in ('CodexAttachments.swift','CodexTelemetry.swift','NativeCodex.swift'))
    (path/'main.swift').write_text(source+HARNESS)
    (path/'server.py').write_text(SERVER)
    result=subprocess.run(['xcrun','swiftc','-swift-version','5','-O','-module-cache-path',str(path/'cache'),str(path/'main.swift'),'-o',str(path/'client')],capture_output=True,text=True,timeout=180)
    assert result.returncode==0,result.stderr
    return path

@pytest.mark.parametrize('mode',['missing','slow','slow_factory','auth','no_handshake','malformed','oversized','stderr','exit','eof','timeout','cancel','cancel_launch','double','retry','stale','success','fragmented','backpressure','request_timeout','history_large','history_read_error','history_activity_error','history_reconnect'])
def test_faults_keep_appkit_responsive_and_owned_children_reaped(compiled,tmp_path,mode):
    result=subprocess.run([str(compiled/'client'),str(tmp_path),mode,sys.executable,str(compiled/'server.py'),str(ROOT/'static_cockpit')],capture_output=True,text=True,timeout=25)
    assert result.returncode==0,result.stderr
    assert f'CONNECTION_PASS {mode}' in result.stdout
    calls=[json.loads(x) for x in (tmp_path/'methods.jsonl').read_text().splitlines()] if (tmp_path/'methods.jsonl').exists() else []
    assert not any(x['method'] in ['turn/start','thread/start','thread/resume','thread/queue/add','account/login/start'] for x in calls)
    assert len({x['pid'] for x in calls})<= (2 if mode in ('retry','history_reconnect') else 1)
    if mode.startswith('history_'):
        history=[x['params'] for x in calls if x['method']=='thread/turns/list']
        assert history and all(x['itemsView'] in ('summary','notLoaded') for x in history)
        assert history[0]['itemsView']=='summary'
        if mode!='history_read_error':
            assert any(x['itemsView']=='notLoaded' for x in history)
            assert any(x.get('cursor')=='older-page' for x in history)
            pages=[x['params'] for x in calls if x['method']=='thread/items/list']
            assert pages and all(x['limit']==5 and x['threadId']=='00000000-0000-4000-8000-000000000001' for x in pages)
    for pid in {x['pid'] for x in calls}:
        with pytest.raises(ProcessLookupError):os.kill(pid,0)
    print(result.stdout.strip())
