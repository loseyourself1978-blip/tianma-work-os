"""Production report and lifecycle code with synthetic provider replies; no model calls."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Production Swift/macOS file publication")


def team_model_source():
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
    swift += "\n".join((src / n).read_text() for n in ("TeamReport.swift","TeamRun.swift","TeamConversation.swift","TeamArtifacts.swift"))
    return swift


def test_approved_team_freeze_review_delivery(tmp_path):
    swift = team_model_source()
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

def test_generic_chat_rounds_recipient_snapshots_and_output_conflicts(tmp_path):
    source = tmp_path / "main.swift"
    source.write_text(team_model_source() + r'''
let url=URL(fileURLWithPath:CommandLine.arguments[1])
var st=stat();precondition(lstat(url.path,&st)==0)
let folder=CodexDirectory(path:url.path,device:UInt64(st.st_dev),inode:UInt64(st.st_ino),isolated:false)
let members=zip(TeamConversation.slots,TeamConversation.portraits).map { slot,name in
    TeamMember(role:slot,product:slot=="Reviewer" ? "Claude":"Codex",provider:slot=="Reviewer" ? "Anthropic":"OpenAI",model:slot+"Model",displayName:name.capitalized,duties:[slot])
}
try TeamConversation.checkedRoster(members)
precondition((try? TeamConversation.checkedRoster(members+[members[0]]))==nil)
func room()->TeamRun {
    var r=TeamRun(id:UUID().uuidString,created:0,goal:"",csv:"",folder:folder,members:members)
    r.conversation=TeamConversation();return r
}
func deliver(_ r:inout TeamRun,_ obj:[String:Any],actual:String?=nil)throws {
    let prompt=try r.prompt(),a=try r.begin(prompt)
    precondition((try? r.begin(prompt))==nil)
    let text=String(decoding:try JSONSerialization.data(withJSONObject:obj),as:UTF8.self)
    try r.receive(id:a.id,text:text,actual:actual ?? a.memberSnapshot!.model,source:"fixture",thread:"isolated-"+r.id,turn:a.id)
    precondition((try? r.receive(id:a.id,text:text,actual:"stale",source:"fixture",thread:"other",turn:a.id))==nil)
}
func submit(_ r:inout TeamRun,_ body:String,_ recipients:[String]=[])throws {
    var c=r.conversation!;var draft=c.draft;draft.text=body;draft.recipients=recipients
    try c.submit(draft,members:r.members,language:"en")
    try c.submit(draft,members:r.members,language:"en")
    draft.text+=" changed";precondition((try? c.submit(draft,members:r.members,language:"en"))==nil)
    r.conversation=c;r.selectNextChatStep()
}
// Exercise submission before persistence, as a room resuming with frozen files would.
func testLargeEvidence() throws {
    let r=room()
    let artifact=String(repeating:"0123456789",count:15800)
    let original=[ "site.js":artifact ]
    var c=r.conversation!
    let revision=TeamFileRevision(id:"frozen",round:c.round,producer:"Builder",attempt:"attempt",
                                  time:0,files:original,digest:"digest")
    c.revisions=[revision]
    var draft=c.draft
    draft.text=String(repeating:"large supplementary evidence ",count:530)
    let uniqueRequirement=String(repeating:"previous requirement ",count:60)
    c.plans=[TeamChatPlan(round:c.round,requirements:[uniqueRequirement],builder:"Builder",reviewer:"Reviewer")]
    try c.submit(draft,members:r.members,language:"en")
    let prompt=try c.prompt(for:c.queue[0],members:r.members)
    let data=Data(prompt[prompt.range(of:"one JSON object.\n")!.upperBound...].utf8)
    let payload=try JSONSerialization.jsonObject(with:data) as! [String:Any]
    let body=draft.text.trimmingCharacters(in:.whitespacesAndNewlines)
    precondition(prompt.utf8.count<=190000 && payload["currentMessage"] as? String==body)
    precondition(payload["frozenFiles"] as? [String:String]==original)
    precondition(payload["assignment"] as? [String:String]==["sameTextAt":"/currentMessage"])
    precondition(payload["userMessages"] as? [[String:String]]==[["sameTextAt":"/currentMessage"]])
    precondition(payload["requirements"] as? [String]==[uniqueRequirement])
    try c.submit(draft,members:r.members,language:"en")
    precondition(c.queue.count==1)
    var impossible=c.draft
    impossible.text=String(repeating:"a different follow-up ",count:1400)
    c.draft=impossible
    do {
        try c.submit(impossible,members:r.members,language:"en")
        preconditionFailure("Unique evidence exceeding the transport limit must be preserved locally")
    } catch TeamError.contextTooLarge {
        precondition(c.draft.key==impossible.key && c.draft.text==impossible.text)
        precondition(c.inputs.count==1 && c.queue.count==1)
    }
}
try testLargeEvidence()
var a=room(),b=room()
try submit(&a,"Explain the difference between grouping and sorting")
try deliver(&a,["mode":"answer","text":"Grouping collects equal keys."])
precondition(a.state=="completed" && a.conversation!.output==nil && a.conversation!.revisions.isEmpty)
try submit(&a,"@ here is plain text, contact user@example.invalid.",["Builder","Tester"])
precondition(a.conversation!.queue.map(\.member)==["Builder","Tester"])
a.members[1].displayName="New name"
precondition(a.conversation!.inputs.last!.members[1].displayName=="Kai")
try deliver(&a,["text":"Reply one"]);try deliver(&a,["text":"Reply two"])
try submit(&b,"Build a brief");precondition(b.conversation!.inputs.count==1 && b.id != a.id)
let plan:[String:Any]=["mode":"plan","text":"Write and inspect the brief.","requirements":["All four sections"],"builder":"Builder","reviewer":"Reviewer"]
try deliver(&b,plan)
for i in 0..<4 {
    try deliver(&b,["text":"Work in progress \(i)","files":["brief.md":"Section \(i)"]])
    let v=b.conversation!.revisions.last!
    try deliver(&b,["text":"Missing section \(i)","digest":v.digest,"verdict":"revise","blocking":[["requirement":"All four sections","location":"brief.md","evidence":"Missing \(i)","fix":"Add section \(i)"]]])
    precondition(b.state=="running" && b.next=="Builder")
}
try deliver(&b,["text":"All sections written","files":["brief.md":"One Two Three Four"]])
let v=b.conversation!.revisions.last!
try deliver(&b,["text":"Four sections present","digest":v.digest,"verdict":"approve","blocking":[]])
precondition(b.state=="awaitingOwner" && b.conversation!.revisions.count==5)
let captured=try TeamFiles.bytes(b)
var restored=try JSONDecoder().decode(TeamRun.self,from:captured)
precondition(restored.conversation!.revisions.last!.digest==v.digest)
try submit(&restored,"Why these sections?");try deliver(&restored,["mode":"answer","text":"Because they address the request."])
precondition(restored.conversation!.revisions.count==5)
restored.conversation!.stoppedByUser=true
precondition(!TeamConversation.authorizesNewRound("Do not continue") && !TeamConversation.authorizesNewRound("为什么不继续") && !TeamConversation.authorizesNewRound("不要继续"))
try submit(&restored,"Why did you stop?");try deliver(&restored,plan)
precondition(restored.conversation!.queue.isEmpty && restored.conversation!.stoppedByUser)
try submit(&restored,"Please resume and add an appendix");try deliver(&restored,plan)
precondition(!restored.conversation!.stoppedByUser && restored.next=="Builder")
// A change between addressing a message and sending cannot redirect it to a replacement.
var changed=room()
try submit(&changed,"Both members should read this",["Builder","Tester"])
var removed=changed.members;removed.removeAll{$0.role=="Builder"}
changed.conversation!.draft.recipients=["Builder"]
try changed.updateChatRoster(removed)
precondition(changed.conversation!.undelivered?.map(\.member)==["Builder"])
precondition(changed.conversation!.queue.map(\.member)==["Tester"] && changed.conversation!.draft.recipients==["Builder"])
try deliver(&changed,["text":"Received by Tester only"])
precondition(changed.attempts.map(\.role)==["Tester"])
var broken=room();try submit(&broken,"Prepare the same outline");try deliver(&broken,plan)
let finding=["requirement":"All four sections","location":"brief.md","evidence":"Section four missing","fix":"Add section four"]
func unchanged(_ r:inout TeamRun)throws{
    try deliver(&r,["text":"Three sections","files":["brief.md":"one two three"]])
    let rev=r.conversation!.revisions.last!
    try deliver(&r,["text":"The last section is missing","verdict":"revise","digest":rev.digest,"blocking":[finding]])
}
try unchanged(&broken);try unchanged(&broken)
precondition(broken.conversation!.queue.first?.kind=="strategy")
var strategy=plan;strategy["text"]="Inspect the source for section four before rebuilding."
try deliver(&broken,strategy);try unchanged(&broken)
precondition(broken.state=="paused" && broken.conversation!.issue!.contains("Section four missing"))
try submit(&broken,"Use the provided fourth section and continue");try deliver(&broken,strategy)
precondition(broken.state=="running" && broken.next=="Builder")
let first=try TeamArtifacts.stage("one",path:"output/brief.md",in:folder,previous:nil)
try TeamArtifacts.commit(first,in:folder);try TeamArtifacts.commit(first,in:folder)
let visible=try TeamArtifacts.visible("output/brief.md",owner:first.file,in:folder)
precondition((try? TeamArtifacts.stage("different room",path:"output/brief.md",in:folder,previous:nil))==nil)
let second=try TeamArtifacts.stage("two",path:"output/brief.md",in:folder,previous:first.file)
try TeamArtifacts.commit(second,in:folder);try TeamArtifacts.commit(second,in:folder)
try Data("Owner's external edit".utf8).write(to:visible)
precondition((try? TeamArtifacts.visible("output/brief.md",owner:second.file,in:folder))==nil)
precondition((try? TeamArtifacts.stage("overwrite",path:"output/brief.md",in:folder,previous:second.file))==nil)
for name in ["../brief","/absolute",".hidden","a/../b","a//b"] {
    precondition((try? TeamArtifacts.validate([name:"data"]))==nil)
}
precondition((try? TeamArtifacts.validate(["Readme.md":"A","README.md":"B"]))==nil)
print("PASS generic discussion, addressed delivery, idempotence, six members, isolated rooms, four revisions, current evidence, continue, stop, recover, direct output and external-edit protection")
''')
    binary = tmp_path / "r2-chat"
    subprocess.run(["xcrun","swiftc","-module-cache-path",str(tmp_path/"cache"),str(source),"-o",str(binary)], check=True, timeout=150)
    output=tmp_path/"chosen folder";output.mkdir()
    result=subprocess.run([str(binary),str(output)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0, result.stderr
    assert "four revisions" in result.stdout
    assert (output/"output/brief.md").read_text()=="Owner's external edit"
