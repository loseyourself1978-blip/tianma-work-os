"""Production report and lifecycle code with synthetic provider replies; no model calls."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Production Swift/macOS file publication")


def test_approved_team_freeze_review_delivery(tmp_path):
    src = ROOT / "packaging/macos"
    # These two values are supplied to the pure state machine by the existing
    # native transport; use the actual serialized types and digest algorithm.
    native = (src / "NativeCodex.swift").read_text()
    integrated = (src / "IntegratedWorkbench.swift").read_text()
    paired = (src / "PairedWorkflow.swift").read_text()
    swift = "import Foundation\nimport Darwin\nimport CryptoKit\n"
    swift += native[native.index("struct CodexDirectory:"):native.index("struct CodexBinding:")]
    swift += "enum NativeCodex { " + next(s.strip() for s in native.splitlines() if "static func digest(_ bytes:" in s) + " }\n"
    swift += paired[paired.index("struct WebTransferFile:"):paired.index("    static func read(")] + "}\n"
    swift += integrated[integrated.index("struct WebHandoffReceipt:"):integrated.index("// Visibility control uses")]
    swift += (src / "TeamReport.swift").read_text() + "\n" + (src / "TeamRun.swift").read_text()
    swift += r'''
let path=CommandLine.arguments[1]
var st=stat();precondition(lstat(path,&st)==0)
let folder=CodexDirectory(path:path,device:UInt64(st.st_dev),inode:UInt64(st.st_ino),isolated:true)
let members=[TeamMember(role:"Planner",product:"Codex",provider:"OpenAI",model:"P"),
             TeamMember(role:"Builder",product:"Codex",provider:"OpenAI",model:"B"),
             TeamMember(role:"Reviewer",product:"Claude web",provider:"Anthropic",model:"R")]
let text=TeamText(en:"Regional sales",zh:"区域销售")
func testRun() throws ->TeamRun {try TeamRun.create(goal:"Synthetic test",csv:TeamFiles.sample,folder:folder,members:members)}
func deliver<T:Encodable>(_ run:inout TeamRun,_ output:T,actual:String?) throws {
    let prompt=try run.prompt(), a=try run.begin(prompt)
    precondition((try? run.begin(prompt))==nil)
    let data=try TeamFiles.json(output)
    try run.receive(id:a.id,text:data,actual:actual,source:actual==nil ? nil:"test",thread:"separate-"+a.role,turn:a.id)
    precondition((try? run.receive(id:a.id,text:data,actual:actual,source:"test",thread:"stale",turn:a.id))==nil)
}
let plan=TeamPlan(builder:text,reviewer:text,acceptance:text)
let webRoster=[TeamMember(role:"Planner", product:"Claude",provider:"Anthropic",model:"Opus 5.5"),members[1],members[2]]
var saved=try TeamRun.create(goal:"Saved public plan",csv:TeamFiles.sample,folder:folder,members:webRoster)
let planPrompt=try saved.prompt(), assign=try saved.begin(planPrompt)
let smartPlan=try TeamFiles.json(plan).replacingOccurrences(of:"\"",with:"”")
let approvedClaude=TeamMember(role:"Builder",product:"Claude",provider:"Anthropic",model:"Opus 5.5 超高")
precondition(approvedClaude.acceptsSelection("Opus 5.5 中等") && approvedClaude.acceptsSelection("Opus 5.5 Extra high"))
precondition(!approvedClaude.acceptsSelection("Sonnet 5.5 中等") && !approvedClaude.acceptsSelection("Opus 5.6 中等") && !approvedClaude.acceptsSelection("中等"))
let smartText = #"{"en":"Keep “North” unchanged","zh":"保留原文"}"#
let decodedText=try TeamFiles.decodeWebContent(TeamText.self,smartText)
precondition(decodedText.en=="Keep “North” unchanged")
precondition((try? TeamFiles.decode(TeamPlan.self,smartPlan))==nil)
var wr=WebHandoffReceipt(source:"team:"+saved.id,message:assign.id,text:planPrompt,hash:assign.inputHash,provider:"Claude",targetPane:0,targetURL:"https://claude.ai/new",binding:saved.id)
wr.resolvedURL="https://claude.ai/chat/engineering";wr.result=smartPlan
saved.attempts[0].web=wr
saved.attempts[0].resultHash=NativeCodex.digest(Data(smartPlan.utf8));saved.attempts[0].replyText=smartPlan
saved.attempts[0].thread=wr.resolvedURL;saved.attempts[0].turn="exact-original-reply"
saved.attempts[0].state="completed";saved.attempts[0].finished=42
saved.state="blocked";saved.reason="invalidReply"
var altered=saved;altered.attempts[0].replyText="Different contents"
precondition(!altered.canRecoverMemberReply && (try? altered.recoverMemberReply())==nil)
try saved.recoverMemberReply()
precondition(saved.next=="Builder" && saved.state=="paused" && saved.attempts.count==1 && saved.attempts[0].finished==42 && saved.attempts[0].replyText==smartPlan)
precondition(!saved.canRecoverMemberReply)
saved.attempts[0].observedWebSelection="Opus 5.5 超高"
saved.memberSelections=["Planner":"Opus 5.5 中等"]
let roundTrip=try JSONDecoder().decode(TeamRun.self,from:TeamFiles.bytes(saved))
precondition(roundTrip.attempts[0].observedWebSelection=="Opus 5.5 超高" && roundTrip.attempts[0].finished==42)
precondition(roundTrip.memberSelections?["Planner"]=="Opus 5.5 中等" && roundTrip.members.first?.model=="Opus 5.5" && roundTrip.attempts.count==1)


func report(_ south:Int)->TeamReport {TeamReport(title:text,summary:text,rows:[TeamRow(region:"East",cents:320000),TeamRow(region:"South",cents:south)],totalCents:320000+south)}
func review(_ r:TeamRun,_ verdict:String)->TeamReview {TeamReview(digest:r.versions.last!.digest,verdict:verdict,findings:text)}
func usage(_ groups:[[String:Any]])->[String:Any] {["threadUsage":["threadId":"single","groups":groups]]}
precondition(TeamRun.matches(requested:"Opus 5.5 超高",actual:"claude-opus-5-5"))
precondition(TeamRun.matches(requested:"Opus 5.5 中等",actual:"claude-opus-5-5"))
precondition(!TeamRun.matches(requested:"Opus 5.5 高",actual:"claude-opus-5-0"))
let one=usage([["model":"B","totalTokens":40],["model":"B","totalTokens":12]])
precondition(TeamRun.usageModel(one,thread:"single")=="B" && TeamRun.usageModel(one,thread:"other")==nil)
precondition(TeamRun.usageModel(usage([["model":"B","totalTokens":20],["model":"X","totalTokens":11]]),thread:"single")==nil)
precondition(TeamRun.usageModel(usage([["totalTokens":20]]),thread:"single")==nil)
let op=UUID().uuidString
let scope=try TeamFiles.taskDirectory(parent:folder,role:"Builder",operation:op)
let reviewScope=try TeamFiles.taskDirectory(parent:folder,role:"Reviewer",operation:op)
precondition(scope.path==path+"/Builder-"+op && reviewScope.path==path+"/Reviewer-"+op)
precondition((try? TeamFiles.taskDirectory(parent:folder,role:"Unknown",operation:op))==nil)
var r=try testRun()
try deliver(&r,plan,actual:"P");try deliver(&r,report(160000),actual:"B")
let v1=r.versions[0];precondition(v1.review==nil)
let freezeName="TWOS-"+r.id+"-v1-frozen"
try TeamFiles.export(v1.files,to:folder,name:freezeName)
precondition((try? TeamFiles.export(v1.files,to:folder,name:freezeName))==nil)
try deliver(&r,review(r,"approve"),actual:"R")
precondition(r.next=="Builder" && r.versions[0].verified==false && (try? r.delivery())==nil)
try deliver(&r,report(180000),actual:"B")
precondition(r.versions[1].digest != v1.digest && r.versions[1].review==nil)
var stale=r
precondition((try? deliver(&stale,TeamReview(digest:v1.digest,verdict:"approve",findings:text),actual:"R"))==nil)
var invalid=r
let critique="Incorrect formatting with frozen ID "+invalid.versions.last!.digest
let opReview=try invalid.begin(invalid.prompt())
try invalid.receive(id:opReview.id,text:critique,actual:"R",source:"test",thread:"reviewer",turn:"test-turn")
precondition(invalid.versions.last?.unstructuredReview==critique && invalid.versions.last?.review==nil && invalid.next=="Builder" && (try? invalid.delivery())==nil)
precondition(v1.files["dashboard.html"]!.contains("Records / 笔数") && v1.files["dashboard.html"]!.contains("<td>2</td><td>3,200.00"))
var missing=r;try deliver(&missing,review(missing,"approve"),actual:nil)
precondition(missing.state=="blocked" && missing.reason=="identity" && (try? missing.delivery())==nil)
let originalOperations=missing.attempts.map(\.id)
missing.checkModelEvidence();precondition(missing.state=="blocked" && (try? missing.delivery())==nil)
missing.attempts[missing.attempts.count-1].model="DIFFERENT";missing.attempts[missing.attempts.count-1].source="test";missing.checkModelEvidence()
precondition(missing.state=="blocked")
missing.attempts[missing.attempts.count-1].model="R";missing.checkModelEvidence()
precondition(missing.state=="awaitingOwner" && missing.attempts.map(\.id)==originalOperations && missing.owner=="pending")
var retry=r
try deliver(&retry,review(retry,"revise"),actual:"R");try deliver(&retry,report(180000),actual:"B");try deliver(&retry,review(retry,"revise"),actual:"R")
precondition(retry.state=="blocked" && retry.attempts.count==7)
var paused=r;paused.state="paused";precondition((try? paused.begin("never dispatch"))==nil)
try deliver(&r,review(r,"approve"),actual:"R");precondition(r.state=="awaitingOwner" && r.owner=="pending")
let work=try TeamFiles.workFolder(for:r)
precondition(work.path==r.workPath && work.path.hasPrefix(path+"/.twos-work-"))
let wi=try TeamFiles.taskDirectory(parent:work,role:"Reviewer",operation:UUID().uuidString)
precondition(wi.path.hasPrefix(work.path+"/Reviewer-"))
let unique=try r.delivery()
let url=URL(fileURLWithPath:path)
let prior=url.appendingPathComponent("existing-owner-file")
try Data("keep".utf8).write(to:prior)
let existing=r.deliveryName
precondition(existing=="Delivery-"+r.id)
try TeamFiles.export(unique,to:folder,name:existing)
var otherRun=try testRun()
precondition(otherRun.deliveryName != existing)
try deliver(&otherRun,plan,actual:"P")
try deliver(&otherRun,report(180000),actual:"B")
try deliver(&otherRun,review(otherRun,"approve"),actual:"R")
let secondFiles=try otherRun.delivery()
try TeamFiles.export(secondFiles,to:folder,name:otherRun.deliveryName)
for (runName, expected) in [(existing,unique),(otherRun.deliveryName,secondFiles)] {
    let output=url.appendingPathComponent(runName)
    let actualNames=try FileManager.default.contentsOfDirectory(atPath:output.path)
    precondition(Set(actualNames)==Set(expected.keys))
    for (name,body) in expected {
        let content=try String(contentsOf:output.appendingPathComponent(name))
        precondition(content==body)
    }
}
let occupied=try testRun()
let refused=url.appendingPathComponent(occupied.deliveryName)
try FileManager.default.createSymbolicLink(at:refused,withDestinationURL:url)
precondition((try? TeamFiles.export(unique,to:folder,name:occupied.deliveryName))==nil)
let retained=try String(contentsOf:prior)
precondition(retained=="keep" && !FileManager.default.fileExists(atPath:url.appendingPathComponent("dashboard.html").path))
var v2=r;v2.layoutVersion=2
precondition(v2.deliveryName=="Delivery" && v2.workPath==r.workPath)

try TeamFiles.export(unique,to:folder,name:"Delivery")
var decided=r; decided.owner="accepted";decided.state="accepted"
let decision=try decided.delivery()
try TeamFiles.updateDecision(in:folder,leaf:"Delivery",previous:unique["delivery.json"]!,next:decision["delivery.json"]!)
try TeamFiles.updateDecision(in:folder,leaf:"Delivery",previous:unique["delivery.json"]!,next:decision["delivery.json"]!)
let acceptedPath=URL(fileURLWithPath:path).appendingPathComponent("Delivery/delivery.json")
let savedDecision=try String(contentsOf:acceptedPath)
precondition(savedDecision==decision["delivery.json"])
try Data("Owner edit".utf8).write(to:acceptedPath)
precondition((try? TeamFiles.updateDecision(in:folder,leaf:"Delivery",previous:unique["delivery.json"]!,next:decision["delivery.json"]!))==nil)
let alternate=[TeamMember(role:"Planner",product:"ChatGPT",provider:"OpenAI",model:"P"),
  TeamMember(role:"Builder",product:"DeepSeek",provider:"DeepSeek",model:"B"),
  TeamMember(role:"Reviewer",product:"Codex",provider:"OpenAI",model:"R")]
var chat=try TeamRun.create(goal:"Alternate roster",csv:TeamFiles.sample,folder:folder,members:alternate)
let key=UUID().uuidString
try chat.addMessage(id:key,text:"Use whole cents",share:true)
try chat.addMessage(id:key,text:"Use whole cents",share:true)
try chat.addMessage(id:UUID().uuidString,text:"Private note",share:false)
let effective=try chat.prompt()
precondition(chat.messages?.count==2 && effective.contains("Use whole cents") && !effective.contains("Private note"))
let legacy=try JSONSerialization.jsonObject(with:TeamFiles.bytes(r)) as! [String:Any]
var older=legacy;older.removeValue(forKey:"layoutVersion")
let restored=try JSONDecoder().decode(TeamRun.self,from:JSONSerialization.data(withJSONObject:older))
precondition(restored.workPath==folder.path)
let files=try r.delivery(),name="TWOS-"+r.id+"-v2-reviewed"
try TeamFiles.export(files,to:folder,name:name)
precondition((try? TeamFiles.export(files,to:folder,name:name))==nil)
let other=CodexDirectory(path:path,device:folder.device,inode:folder.inode+1,isolated:true)
precondition((try? TeamFiles.export(files,to:other,name:"TWOS-"+r.id+"-v2-accepted"))==nil)
precondition((try? TeamFiles.totals("region,amount\nX,1.001"))==nil)
let cents=try TeamFiles.totals("region,amount\nX,0.10\nX,0.20");precondition(cents["X"]==30)
let escaped=try TeamFiles.artifacts(TeamReport(title:TeamText(en:"<script>",zh:"测试"),summary:text,rows:report(180000).rows,totalCents:500000),csv:TeamFiles.sample)
precondition(escaped["dashboard.html"]!.contains("&lt;script&gt;"))
print(name)
'''
    source = tmp_path / "main.swift"
    source.write_text(swift)
    binary = tmp_path / "report-check"
    folder = tmp_path / "output"
    folder.mkdir()
    subprocess.run(["xcrun","swiftc","-module-cache-path",str(tmp_path/"module-cache"),str(source),"-o",str(binary)], check=True, timeout=120)
    leaf = subprocess.check_output([str(binary),str(folder)],text=True,timeout=20).strip()
    result = folder / leaf
    manifest = json.loads((result / "delivery.json").read_text())
    assert manifest["regionalCents"] == {"East":320000,"South":180000}
    assert manifest["ownerDecision"] == "pending"
    import hashlib
    for name, digest in manifest["sha256"].items():
        data = (result / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest
        assert "区域销售" in data.decode()
