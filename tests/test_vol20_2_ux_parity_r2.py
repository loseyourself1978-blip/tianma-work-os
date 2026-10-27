"""R2 focused native parser/observability checks. Synthetic service, real parsers.

No Owner data, credentials, account RPC, or model requests are used by this suite.
Actual protocol and GUI evidence are recorded separately.
"""
from pathlib import Path
import json
import subprocess
import sys
import zipfile
import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='Native macOS client')

def test_native_catalog_preserves_launcher_dictionary_contract():
    catalog=json.loads((ROOT/'static_cockpit/project_first/native_i18n.json').read_text())
    # One malformed entry makes Swift's whole dictionary cast fail, disabling
    # translations even when the persisted language preference remains correct.
    assert all(isinstance(v,dict) and all(isinstance(v.get(k),str) and v[k] for k in ('en-US','zh-CN')) for v in catalog.values())

@pytest.fixture(scope='module')
def r2_binary(tmp_path_factory):
    root=tmp_path_factory.mktemp('r2-native')
    code=(ROOT/'packaging/macos/TianmaLauncher.swift').read_text().split('// The only child runtime',1)[0]
    for name in ['CodexAttachments.swift','CodexTelemetry.swift','NativeCodex.swift']:
        code+='\n'+(ROOT/'packaging/macos'/name).read_text()
    code+=r'''
import CoreText
let app=NSApplication.shared
let root=URL(fileURLWithPath:CommandLine.arguments[1])
let resources=URL(fileURLWithPath:CommandLine.arguments[2])
let mode=CommandLine.arguments[3]
try NativeWorkbench.safeDirectory(root)
if mode == "fixture-images" {
    let image=NSBitmapImageRep(bitmapDataPlanes:nil,pixelsWide:12,pixelsHigh:12,bitsPerSample:8,samplesPerPixel:3,hasAlpha:false,isPlanar:false,colorSpaceName:.deviceRGB,bytesPerRow:0,bitsPerPixel:0)!
    for x in 0..<12 { for y in 0..<12 { image.setColor(NSColor(deviceRed:0,green:0,blue:1,alpha:1),atX:x,y:y) } }
    try image.representation(using:.png,properties:[:])!.write(to:root.appendingPathComponent("样本.png"))
    try image.representation(using:.jpeg,properties:[:])!.write(to:root.appendingPathComponent("样本.jpeg"))
    let data=NSMutableData(),consumer=CGDataConsumer(data:NSMutableData() as CFMutableData)
    var rect=CGRect(x:0,y:0,width:300,height:180)
    let writer=CGDataConsumer(data:data as CFMutableData)!, ctx=CGContext(consumer:writer,mediaBox:&rect,nil)!
    ctx.beginPDFPage(nil);ctx.textPosition=CGPoint(x:20,y:90)
    let line=CTLineCreateWithAttributedString(NSAttributedString(string:"R2PDFTEXT",attributes:[.font:NSFont.systemFont(ofSize:14)]))
    CTLineDraw(line,ctx);ctx.endPDFPage();ctx.closePDF()
    try (data as Data).write(to:root.appendingPathComponent("样本.pdf"))
    _ = consumer
    exit(0)
}
if mode == "parse" {
    let file=URL(fileURLWithPath:CommandLine.arguments[4])
    do {
        let parsed=try CodexAttachmentParser.parse(name:file.lastPathComponent,bytes:Data(contentsOf:file),scratch:root.appendingPathComponent("scratch"))
        let result:[String:Any]=["coverage":parsed.coverage,"mime":parsed.mime,"text":parsed.mime.hasPrefix("image/") ? "IMAGE" : String(decoding:parsed.bytes,as:UTF8.self),"sourceBytes":parsed.sourceBytes]
        print(String(decoding:try JSONSerialization.data(withJSONObject:result),as:UTF8.self))
    } catch { print("ERROR:"+((error as? CodexAttachmentFailure)?.rawValue ?? "unknown")) }
    exit(0)
}
var client=NativeCodex(resources:resources,preferences:root.appendingPathComponent("prefs"),translate:{$0})
client.connected=true;client.selected=["id":"thread-a","cwd":root.path];client.turnID="turn-a"
func reply(_ method:String,_ value:[String:Any]) {
    let id=client.requestMethods.keys.first{client.requestMethods[$0]==method}!
    client.receive(try! JSONSerialization.data(withJSONObject:["id":id,"result":value])+Data([10]))
}
func ev(_ method:String,_ params:[String:Any],_ rid:Int?=nil) {
    var data:[String:Any]=["method":method,"params":params];if let rid=rid {data["id"]=rid}
    client.receive(try! JSONSerialization.data(withJSONObject:data)+Data([10]))
}
if mode == "usage" {
    client.refreshUsage()
    precondition(Set(client.requestMethods.values)==["account/read"])
    reply("account/read",["account":["type":"chatgpt","planType":"pro"],"workspaceRouting":["chatgptAccountId":"a","backendOrigin":"service"]])
    let limits:[String:Any]=["accountId":"a","rateLimits":["limitId":"codex","primary":["usedPercent":25,"windowDurationMins":10080,"resetsAt":2000],"secondary":NSNull()],"rateLimitsByLimitId":["codex":["primary":["usedPercent":25,"windowDurationMins":10080,"resetsAt":2000]]]]
    reply("account/rateLimits/read",limits);reply("account/usage/read",["summary":["lifetimeTokens":100],"dailyUsageBuckets":[["startDate":"2026-10-20","tokens":100]]])
    precondition(client.accountVerified && client.telemetry.limits != nil && client.telemetry.usage != nil)
    let previous=client.requestID;client.refreshUsage();precondition(client.requestID==previous,"manual refresh is throttled")
    let total=["inputTokens":100,"cachedInputTokens":40,"cacheWriteInputTokens":0,"outputTokens":30,"reasoningOutputTokens":10,"totalTokens":130]
    for _ in 0..<3 {ev("thread/tokenUsage/updated",["threadId":"thread-a","turnId":"turn-a","tokenUsage":["total":total,"last":total]])}
    precondition(client.telemetry.tokens["thread-a"]?.total["totalTokens"]==130,"snapshots replace, never add cache/reasoning")
    ev("thread/tokenUsage/updated",["threadId":"foreign","turnId":"foreign","tokenUsage":["total":["totalTokens":999]]])
    precondition(client.telemetry.tokens.count==1)
    client.usageRequestedAt=0;client.refreshUsage()
    reply("account/read",["account":["type":"chatgpt","planType":"plus"],"workspaceRouting":["chatgptAccountId":"b","backendOrigin":"service"]])
    precondition(client.telemetry.limits==nil && client.telemetry.tokens.isEmpty,"account switch removes old account values")
    reply("account/rateLimits/read",["accountId":"b","rateLimits":["primary":NSNull(),"secondary":NSNull()]])
    let errorID=client.requestMethods.keys.first{client.requestMethods[$0]=="account/usage/read"}!
    client.receive(try! JSONSerialization.data(withJSONObject:["id":errorID,"error":["code":-32601,"message":"Method not found"]])+Data([10]))
    precondition(client.usageErrors["usage"]=="unsupported" && !client.usageReading)
    precondition(NativeCodex.telemetryError("at capacity")=="capacity")
    precondition(NativeCodex.telemetryError("quota exhausted")=="quota")
    precondition(NativeCodex.telemetryError("rate limit 429")=="rate_limit")
    precondition(NativeCodex.telemetryError("authentication 401")=="authentication")
    precondition(NativeCodex.telemetryError("network timeout")=="network")
    client.telemetry.limits=try! JSONSerialization.data(withJSONObject:["rateLimits":["primary":["resetsAt":1000.0]]]);client.telemetry.limitsUpdated=900
    precondition(client.quotaResetNeedsRead(now:1001),"expired window triggers service read, not invented full balance")
    client.telemetry.limitsUpdated=1002;precondition(!client.quotaResetNeedsRead(now:1003),"fresh service snapshot controls reset")
    let trusted=client.telemetry.limits
    client.usageRequestedAt=0;client.refreshUsage()
    let networkID=client.requestMethods.keys.first{client.requestMethods[$0]=="account/read"}!
    client.receive(try! JSONSerialization.data(withJSONObject:["id":networkID,"error":["code":-1,"message":"network timeout"]])+Data([10]))
    precondition(client.telemetry.limits==trusted && client.accountVerified && client.usageErrors["account"]=="network" && client.usageRetryAfter>0,"network failure retains dated trusted scope and backs off")
    client.usageRequestedAt=0;client.refreshUsage();client.usageGeneration+=1;client.usageReading=false
    reply("account/read",["account":["type":"chatgpt","planType":"plus"],"workspaceRouting":["chatgptAccountId":"ignored-cancelled","backendOrigin":"service"]])
    precondition(client.requestMethods.isEmpty && client.telemetry.limits==trusted,"cancelled refresh cannot enqueue dependent reads or overwrite account cache")
    client.usageRequestedAt=0;client.refreshUsage()
    let authID=client.requestMethods.keys.first{client.requestMethods[$0]=="account/read"}!
    client.receive(try! JSONSerialization.data(withJSONObject:["id":authID,"error":["code":401,"message":"authentication failed"]])+Data([10]))
    precondition(!client.accountVerified,"auth failure hides old account values")
    precondition(client.requestMethods.isEmpty,"no turn, purchase, reset, or email RPC was generated")
    client.saveTelemetry()
    let restored=NativeCodex(resources:resources,preferences:root.appendingPathComponent("prefs"),translate:{$0})
    precondition(!restored.accountVerified && restored.telemetry.accountIdentity==client.telemetry.accountIdentity,"cache is gated until account verified")
} else if mode == "runtime" {
    client.observeEvent("turn/started",["threadId":"thread-a","turn":["id":"turn-a","startedAt":100.0]],now:100)
    let key="thread-a/turn-a"
    let directory=try NativeCodex.inspectDirectory(root.path,isolated:false)
    var initial=CodexSubmission(id:"initial",thread:"thread-a",directory:directory,text:"",attachments:[],model:"model-a",effort:"low",mode:"steer",createdAt:90,source:nil,message:nil,instructionHash:nil,state:"running")
    initial.turn="turn-a";client.ledger.submissions=[initial]
    precondition(client.observedSubmission(for:client.telemetry.runs[key]!)?.createdAt==90,"idle default Steer still starts the primary turn")
    let image=CodexAttachment(id:"image",name:"中文.png",mime:"image/png",base64:Data([1,2,3]).base64EncodedString(),transportVersion:3)
    precondition(image.inputs.count==2 && (image.inputs[0]["text"] as? String)?.contains("中文.png")==true && image.inputs[1]["type"] as? String=="image")
    var legacy=image;legacy.transportVersion=2;precondition(legacy.inputs.count==1,"retained attachment wire identity stays unchanged")
    client.observationTick=100;client.tickObservations(uptime:102);client.observationTick=ProcessInfo.processInfo.systemUptime
    precondition(client.telemetry.runs[key]!.activeSeconds==2)
    client.observeEvent("item/tool/requestUserInput",["threadId":"thread-a","turnId":"turn-a"],requestID:12,now:103)
    client.observationTick=103;client.tickObservations(uptime:105);client.observationTick=ProcessInfo.processInfo.systemUptime
    precondition(client.telemetry.runs[key]!.waitSeconds==2)
    precondition(client.telemetry.runs[key]!.estimate(now:105,online:true)["reason"] as? String == "waiting_user")
    client.observeEvent("serverRequest/resolved",["threadId":"thread-a","requestId":12],now:106)
    precondition(client.telemetry.runs[key]!.requests.isEmpty,"schema lacks turnId; resolve by exact request identity")
    client.observeEvent("item/commandExecution/requestApproval",["threadId":"thread-a","turnId":"turn-a"],requestID:13,now:106)
    precondition(client.telemetry.runs[key]!.requests["13"]=="waiting_approval" && client.telemetry.runs[key]!.estimate(now:106,online:true)["reason"] as? String=="waiting_user")
    client.observeEvent("serverRequest/resolved",["threadId":"thread-a","requestId":13],now:106)

    for _ in 0..<3 {client.observeEvent("item/started",["threadId":"thread-a","turnId":"turn-a","item":["id":"cmd","type":"commandExecution"]],now:106)}
    precondition(client.telemetry.runs[key]!.tools.count==1 && client.telemetry.runs[key]!.activeTools.count==1)
    client.observeEvent("item/started",["threadId":"child","turnId":"child","item":["id":"childcmd","type":"commandExecution"]],now:106)
    precondition(client.telemetry.runs.count==1,"child time is not added to parent")
    client.observeEvent("error",["threadId":"thread-a","turnId":"turn-a","willRetry":true],now:107)
    let activeBefore=client.telemetry.runs[key]!.activeSeconds
    client.observationTick=107;client.tickObservations(uptime:109);client.observationTick=ProcessInfo.processInfo.systemUptime
    precondition(client.telemetry.runs[key]!.activeSeconds==activeBefore && client.telemetry.runs[key]!.estimate(now:109,online:true)["reason"] as? String=="offline","service reconnect is not active model time or reliable ETA")
    client.observeEvent("item/agentMessage/delta",["threadId":"thread-a","turnId":"turn-a","itemId":"response","delta":"resumed"],now:110)
    precondition(client.telemetry.runs[key]!.serviceInterrupted==false,"real activity resumes observation")
    var run=client.telemetry.runs[key]!
    run.activeSeconds=0;run.planUpdate([["step":"a","status":"inProgress"],["step":"b","status":"pending"],["step":"c","status":"pending"]])
    run.activeSeconds=10;run.planUpdate([["step":"a","status":"completed"],["step":"b","status":"inProgress"],["step":"c","status":"pending"]])
    run.activeSeconds=30;run.planUpdate([["step":"a","status":"completed"],["step":"b","status":"completed"],["step":"c","status":"inProgress"]])
    run.lastActivity=100
    precondition(run.stepSamples==[10,20])
    precondition(run.estimate(now:100,online:true)["available"] as? Bool == true)
    run.planUpdate([["step":"a","status":"completed"],["step":"b","status":"completed"],["step":"c","status":"inProgress"],["step":"d","status":"pending"]])
    precondition(run.planRevisions==2 && run.stepSamples.count==2)
    run.activeSeconds=100
    precondition(run.estimate(now:100,online:true)["reassessed"] as? Bool == true)
    precondition(run.estimate(now:400,online:true)["reason"] as? String == "stale_activity")
    precondition(run.estimate(now:100,online:false)["reason"] as? String == "offline")
    run.planUpdate([]);precondition(run.estimate(now:100,online:true)["reason"] as? String == "unknown_remaining_work")
    client.observeEvent("turn/completed",["threadId":"thread-a","turn":["id":"turn-a","status":"completed","durationMs":10000,"completedAt":110]],now:110)
    let finished=client.telemetry.runs[key]!
    precondition(finished.wallTimes(submitted:90,now:500)["sinceSubmission"] as? Double == 20,"terminal wall elapsed freezes")
    precondition(finished.wallTimes(submitted:200,now:1)["beforeStart"] as? Double == 0,"clock changes never show negative durations")
    precondition(finished.wallTimes(submitted:nil,now:500)["sinceSubmission"] is NSNull,"unknown timestamps are not zero")
    client.observeEvent("turn/started",["threadId":"thread-a","turn":["id":"turn-a"]],now:500)
    client.observationTick=100;client.tickObservations(uptime:10000)
    precondition(client.telemetry.runs[key]!.ended==finished.ended && client.telemetry.runs[key]!.activeSeconds==finished.activeSeconds,"terminal freezes despite duplicate events")
    client.saveTelemetry()
    let restarted=NativeCodex(resources:resources,preferences:root.appendingPathComponent("prefs"),translate:{$0})
    precondition(restarted.telemetry.runs[key]!.terminal && restarted.requestID==0,"restart observes; no implicit run")
} else if mode == "increment" {
    // TEST/FIXTURE metadata only; no service connection or model requests.
    var run=CodexRunObservation(thread:"fixture",turn:"fixture",lastActivity:100)
    func steps(_ states:[String])->[[String:Any]] { states.enumerated().map { ["step":"Test step \($0.offset)","status":$0.element] } }
    func remaining(_ run:CodexRunObservation)->Double? {run.workload(now:100,online:true)["remainingPercent"] as? Double}
    precondition(remaining(run)==nil && run.estimate(now:100,online:true)["available"] as? Bool == false)
    run.planUpdate(steps(["completed","inProgress","pending","pending"]))
    precondition(remaining(run)==75 && run.planRevisions==1,"in progress does not count as half")
    let same=run;run.planUpdate(steps(["completed","inProgress","pending","pending"]))
    precondition(run.planRevisions==same.planRevisions && run.stepSamples==same.stepSamples,"duplicate plan is idempotent")
    run.planUpdate(steps(["completed","completed","pending","pending"]))
    precondition(remaining(run)==50)
    run.planUpdate(steps(["completed","completed","pending","pending","pending"]))
    precondition(remaining(run)==60 && run.planRevisions==2,"new work increases remaining estimate")
    run.planUpdate(steps(["completed","pending","pending","pending","pending"]))
    precondition(remaining(run)==80 && run.planRevisions==3,"reopen changes plan version")
    run.planUpdate(steps(["completed","pending"]))
    precondition(remaining(run)==50 && run.planRevisions==4)
    run.state="failed";precondition(remaining(run)==50);run.state="cancelled";precondition(remaining(run)==50)
    run.state="completed";precondition(remaining(run)==0 && run.estimate(now:100,online:true)["reason"] as? String=="terminal")
    run.state="running";run.planUpdate(steps(["unexpected"]));precondition(remaining(run)==nil)
    run.planUpdate(steps(["inProgress","pending"]));run.stepSamples=[10,20]
    precondition(run.estimate(now:100,online:true)["low"] as? Double==24 && run.estimate(now:100,online:true)["high"] as? Double==72)
    run.requests=["request":"waiting_input"];precondition(run.estimate(now:100,online:true)["reason"] as? String=="waiting_user")
    run.requests=[:];precondition(run.estimate(now:100,online:false)["reason"] as? String=="offline")
    precondition(run.workload(now:400,online:true)["stale"] as? Bool==true && run.estimate(now:400,online:true)["reason"] as? String=="stale_activity")
    run.stepSamples=[1,100];precondition(run.estimate(now:100,online:true)["reason"] as? String=="heterogeneous_samples")
    run.stepSamples=[10,20];run.activeSeconds=200;run.activeTools=["long-tool"]
    precondition(run.estimate(now:100,online:true)["reassessed"] as? Bool==true)
    let saved=try JSONEncoder().encode(run);let restored=try JSONDecoder().decode(CodexRunObservation.self,from:saved)
    precondition(remaining(restored)==remaining(run) && restored.planRevisions==run.planRevisions && restored.activeSeconds==200)
    precondition(client.requestID==0,"all new metrics are observation-only")
} else if mode == "directories" {
    let empty=root.appendingPathComponent("existing-empty"), project=root.appendingPathComponent("existing-project")
    try FileManager.default.createDirectory(at:empty,withIntermediateDirectories:true)
    try FileManager.default.createDirectory(at:project,withIntermediateDirectories:true)
    try Data("preserve".utf8).write(to:project.appendingPathComponent("existing.txt"))
    let _=try NativeCodex.inspectDirectory(empty.path,isolated:true,requireEmpty:true)
    let d=try NativeCodex.inspectDirectory(project.path,isolated:false,requireEmpty:false)
    let original=try Data(contentsOf:project.appendingPathComponent("existing.txt"));precondition(String(decoding:original,as:UTF8.self)=="preserve")
    do {let _=try NativeCodex.inspectDirectory(project.path,isolated:true,requireEmpty:true);fatalError("nonempty incorrectly accepted")}catch{}
    try FileManager.default.setAttributes([.posixPermissions:0o500],ofItemAtPath:empty.path)
    do {let _=try NativeCodex.inspectDirectory(empty.path,isolated:true,requireEmpty:true);fatalError("read-only folder incorrectly accepted")}catch{}
    try FileManager.default.setAttributes([.posixPermissions:0o700],ofItemAtPath:empty.path)
    do {let _=try NativeCodex.inspectDirectory(root.appendingPathComponent("missing").path,isolated:true);fatalError("missing folder incorrectly accepted")}catch{}
    let link=root.appendingPathComponent("link");try FileManager.default.createSymbolicLink(at:link,withDestinationURL:project)
    let resolved=try NativeCodex.inspectDirectory(link.path,isolated:false);precondition(resolved.path==project.path && resolved.inode==d.inode,"initial selection displays and binds the resolved directory identity")
    client.ledger.bindings["thread-a"]=CodexBinding(thread:"thread-a",directory:d,permission:"twos-integrated",createdAt:0)
    precondition(client.validBinding(client.ledger.bindings["thread-a"]!))
    let originalCount=client.requestID;client.previewDirectory(d,create:false);client.pendingDirectory=nil
    precondition(client.requestID==originalCount,"preview/cancel neither writes a binding nor starts a model")
    let content=Data("SAME_NAME_SAFE".utf8).base64EncodedString()
    client.importAttachment(name:"同名.md",mime:"",base64:content);client.importAttachment(name:"同名.md",mime:"",base64:content)
    precondition(client.ledger.drafts["thread-a"]?.count==2 && Set(client.ledger.drafts["thread-a"]!.map{$0.id}).count==2,"same names remain independent")
    var bounded=client.ledger.drafts["thread-a"]![0];bounded.sourceBytes=12_000_000
    client.ledger.drafts["thread-a"]=[bounded]
    client.importAttachment(name:"one-more.txt",mime:"",base64:Data("x".utf8).base64EncodedString())
    precondition(client.ledger.drafts["thread-a"]?.count==1 && client.requestID==originalCount,"combined source-byte limit blocks without model request")

}
print("R2_"+mode.uppercased()+"_PASS")
exit(0)
'''
    source=root/'main.swift';source.write_text(code)
    binary=root/'r2-tests'
    out=subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(root/'cache'),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120)
    assert out.returncode==0,out.stderr
    return binary

@pytest.mark.parametrize('mode',['usage','runtime','directories','increment'])
def test_observation_and_directory_contract(r2_binary,tmp_path,mode):
    out=subprocess.run([str(r2_binary),str(tmp_path/'runtime'),str(ROOT/'static_cockpit'),mode],capture_output=True,text=True,timeout=30)
    assert out.returncode==0,out.stderr
    assert f'R2_{mode.upper()}_PASS' in out.stdout

@pytest.mark.parametrize('ext',['txt','md','json','csv','html','py','swift','docx','xlsx','pptx'])
def test_local_attachment_parse_no_execution(r2_binary,tmp_path,ext):
    file=tmp_path/('中文同名.'+ext);marker='R2_NON_SENSITIVE_附件'
    if ext in {'docx','xlsx','pptx'}:
        paths={'docx':('word/document.xml','<w:document xmlns:w="w"><w:p><w:t>'+marker+'</w:t></w:p></w:document>'),'xlsx':('xl/worksheets/sheet1.xml','<worksheet><row><c r="A1" t="inlineStr"><is><t>'+marker+'</t></is></c><c r="B1"><f>1+1</f><v>2</v></c></row></worksheet>'),'pptx':('ppt/slides/slide1.xml','<p:sld xmlns:p="p" xmlns:a="a"><a:p><a:t>'+marker+'</a:t></a:p></p:sld>')}
        with zipfile.ZipFile(file,'w') as z:
            z.writestr('[Content_Types].xml','<Types/>');z.writestr(*paths[ext])
    else:file.write_text(marker+' <script>not executed</script>',encoding='utf-8')
    before=file.read_bytes()
    out=subprocess.run([str(r2_binary),str(tmp_path/'runtime'),str(ROOT/'static_cockpit'),'parse',str(file)],capture_output=True,text=True,timeout=30)
    assert out.returncode==0,out.stderr
    result=json.loads(out.stdout);assert marker in result['text'] and result['sourceBytes']==len(before)
    assert file.read_bytes()==before
    assert not list((tmp_path/'runtime'/'scratch').glob('*')) if (tmp_path/'runtime'/'scratch').exists() else True

@pytest.mark.parametrize('name,data,expected',[('bad.pdf',b'not a PDF','malformed'),('private.zip',b'zip','unsupported'),('bad.md',b'\xff\x01','encoding'),('empty.txt',b'','empty'),('big.txt',b'x'*200001,'tooLarge'),('utf16.txt','安全中文'.encode('utf-16'),None)],ids=['malformed-pdf','unsupported-archive','invalid-encoding','empty','text-limit','utf16'])
def test_attachment_rejection_and_encoding(r2_binary,tmp_path,name,data,expected):
    file=tmp_path/name;file.write_bytes(data)
    out=subprocess.run([str(r2_binary),str(tmp_path/'runtime'),str(ROOT/'static_cockpit'),'parse',str(file)],capture_output=True,text=True,timeout=30)
    assert out.returncode==0,out.stderr
    if expected:assert 'ERROR:'+expected in out.stdout
    else:assert json.loads(out.stdout)['text']=='安全中文'


def test_image_and_pdf_content_paths(r2_binary,tmp_path):
    made=subprocess.run([str(r2_binary),str(tmp_path/'samples'),str(ROOT/'static_cockpit'),'fixture-images'],capture_output=True,text=True,timeout=30)
    assert made.returncode==0,made.stderr
    for ext in ['png','jpeg','pdf']:
        file=tmp_path/'samples'/('样本.'+ext)
        out=subprocess.run([str(r2_binary),str(tmp_path/'runtime'),str(ROOT/'static_cockpit'),'parse',str(file)],capture_output=True,text=True,timeout=30)
        assert out.returncode==0,out.stderr
        result=json.loads(out.stdout)
        assert result['coverage']=='pdf_text:1/1' and 'R2PDFTEXT' in result['text'] if ext=='pdf' else result['coverage']=='image_native' and result['text']=='IMAGE'

@pytest.mark.parametrize('problem',['parent-path','macro','entity','expanded-limit','duplicate'])
def test_office_document_safety(r2_binary,tmp_path,problem):
    file=tmp_path/'sample.docx'
    with zipfile.ZipFile(file,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<Types/>')
        xml='<doc><t>safe</t></doc>'
        if problem=='entity':xml='<!DOCTYPE doc [<!ENTITY external SYSTEM "file:///nonexistent">]><doc><t>&external;</t></doc>'
        if problem=='expanded-limit':xml='<doc><t>'+'x'*2_000_001+'</t></doc>'
        z.writestr('word/document.xml',xml)
        if problem=='parent-path':z.writestr('../escape','untrusted')
        if problem=='macro':z.writestr('word/vbaProject.bin','untrusted')
        if problem=='duplicate':z.writestr('word/document.xml','<doc/>')
    out=subprocess.run([str(r2_binary),str(tmp_path/'runtime'),str(ROOT/'static_cockpit'),'parse',str(file)],capture_output=True,text=True,timeout=30)
    assert out.returncode==0,out.stderr
    assert 'ERROR:' in out.stdout
    assert not (tmp_path/'escape').exists()
