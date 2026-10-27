"""Production native state machine with synthetic service responses, no model calls.

The 101.38 draft-only handoff and global desktop-running gate are superseded by
folder-bound sessions, writer-lease verification and actual queued delivery.
"""
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='Native macOS client')

@pytest.fixture(scope='module')
def native_client(tmp_path_factory):
    root = tmp_path_factory.mktemp('native-codex-state')
    production = (ROOT/'packaging/macos/TianmaLauncher.swift').read_text().split('// The only child runtime',1)[0]
    production += (ROOT/'packaging/macos/CodexAttachments.swift').read_text()
    production += (ROOT/'packaging/macos/CodexTelemetry.swift').read_text()
    production += (ROOT/'packaging/macos/NativeCodex.swift').read_text()
    harness = r'''
let app = NSApplication.shared
let root = URL(fileURLWithPath: CommandLine.arguments[1])
let resources = URL(fileURLWithPath: CommandLine.arguments[2])
try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
let id = UUID().uuidString, foreign = UUID().uuidString
var client = NativeCodex(resources: resources, preferences: root.appendingPathComponent("prefs"), translate: {$0})
client.connected = true; client.ownerDesktopRunning = {true}
client.modelCatalog = ["model-a", "model-b"].map { ["model": $0, "inputModalities": ["text", "image"], "supportedReasoningEfforts": [["reasoningEffort":"low"],["reasoningEffort":"high"]]] }
client.modelIDs = ["model-a", "model-b"]
func request(_ method: String) -> (Int, [String: Any]) {
    guard let key = client.requestMethods.keys.sorted().first(where: { client.requestMethods[$0] == method }) else { fatalError("Missing request: \(method); pending=\(client.requestMethods)") }
    return (key, client.requestArguments[key]!)
}
func reply(_ method: String, _ value: [String: Any]) {
    let (key, _) = request(method)
    client.receive(try! JSONSerialization.data(withJSONObject: ["id":key, "result":value]) + Data([10]))
}
func reject(_ method: String, _ message: String) {
    let (key, _) = request(method)
    client.receive(try! JSONSerialization.data(withJSONObject: ["id":key, "error":["code":-32600,"message":message]]) + Data([10]))
}
func event(_ method: String, _ params: [String: Any]) {
    client.receive(try! JSONSerialization.data(withJSONObject:["method":method,"params":params]) + Data([10]))
}
func select(_ tid: String) {
    client.selectThread(tid); reply("thread/read", ["thread":["id":tid,"cwd":root.path,"status":["type":"notLoaded"]]])
    reply("thread/turns/list", ["data":[["id":"old-turn","status":"completed","completedAt":10,"items":[]]]])
}
select(foreign)
precondition(!client.canControl && client.historyReady)
let originalRequests = client.requestID
client.sendTurn("Never execute an unbound official App thread", model:"model-a")
precondition(client.requestID == originalRequests && !client.isBusy)
client.saveDraft("Keep the official-thread draft")
// Cancel and forged preview tokens have no file/session effect.
let workspace = root.appendingPathComponent("empty-workspace")
try FileManager.default.createDirectory(at:workspace,withIntermediateDirectories:false)
let directory = try NativeCodex.inspectDirectory(workspace.path, isolated:true, requireEmpty:true)
client.previewDirectory(directory,create:false)
client.confirmDirectory(token:"not-the-confirmed-token",model:"model-a",effort:"low")
precondition(client.requestID == originalRequests && client.threadID == foreign)
let token = client.pendingDirectory!.token
client.confirmDirectory(token:token,model:"model-a",effort:"low")
let (_, creation) = request("thread/start")
precondition(creation["cwd"] as? String == workspace.path && creation["runtimeWorkspaceRoots"] as? [String] == [workspace.path])
precondition(creation["historyMode"] as? String == "paginated" && creation["allowProviderModelFallback"] as? Bool == false)
reply("thread/start", ["thread":["id":id,"cwd":workspace.path,"historyMode":"paginated","canAcceptDirectInput":true,"model":"model-a","status":["type":"idle"]],"model":"model-a","cwd":workspace.path,"runtimeWorkspaceRoots":[workspace.path],"activePermissionProfile":["id":"twos-integrated"]])
reply("thread/name/set", [:])
reply("thread/list", ["data":[]])
precondition(client.threadID == id && client.canControl && client.controlledThreads.contains(id) && client.historyReady)
let initialFiles = try FileManager.default.contentsOfDirectory(atPath:workspace.path)
precondition(initialFiles.isEmpty,"no git init or implicit sample")
// An explicit source instruction becomes a bound immutable input, not a draft.
let source = URL(string:"https://chatgpt.com/c/synthetic-source")!
client.stage("Full instruction\nLast paragraph",source:source,message:"message-1")
precondition(client.handoffCandidate != nil && client.ledger.submissions.isEmpty,"first source/target requires inline confirmation")
client.confirmHandoff(model:"model-a",effort:"low",hash:NativeCodex.digest(Data("Full instruction\nLast paragraph".utf8)))
let handoff = client.ledger.submissions[0]
precondition(handoff.text.hasSuffix("Last paragraph") && handoff.source == source.absoluteString && handoff.directory == directory)
precondition(client.isBusy && client.draftText.isEmpty)
client.stage(handoff.text,source:source,message:"message-1")
client.confirmHandoff(model:"model-a",effort:"low",hash:handoff.instructionHash!)
precondition(client.ledger.submissions.count == 1,"double handoff must not enqueue twice")
reply("thread/settings/update", [:])
reply("thread/read", ["thread":["id":id,"cwd":workspace.path,"historyMode":"paginated","environments":[["environmentId":"local","cwd":workspace.path,"runtimeWorkspaceRoots":[workspace.path]]],"model":"model-a","reasoningEffort":"low","status":["type":"idle"]]])
reply("thread/queue/list", ["data":[]])
let (_, submission) = request("thread/queue/add")
precondition(submission["clientUserMessageId"] as? String == handoff.id)
let sentInput = submission["input"] as! [[String:Any]]
precondition(sentInput[1]["text"] as? String == handoff.text,"original business instruction is intact")
let context = sentInput[0]["text"] as! String
precondition(context.contains(workspace.path) && context.contains(handoff.id) && context.contains(id))
precondition(context.contains("allowed_write_root") && context.contains("writer_lease") && context.contains("不需要也不应寻找内部绑定查询工具"))
precondition(client.ledger.submissions[0].dispatchContext == context,"persist exact context before dispatch")
event("turn/started",["threadId":id,"turn":["id":"turn-1"]])
event("item/started",["threadId":id,"turnId":"turn-1","item":["id":"user-1","type":"userMessage","clientId":handoff.id,"content":[]]])
reply("thread/queue/add", ["queuedSubmission":["id":"queue-main","clientUserMessageId":handoff.id]])
precondition(client.turnID == "turn-1" && !client.startingTurn)
// A switch while active preserves the active task and draft.
client.saveDraft("supplement")
client.selectThread(foreign);precondition(client.threadID == id && client.draftText == "supplement")
client.nextModel = "model-b";client.nextEffort = "high"
client.submitComposer(["text":"supplement","model":"model-b","effort":"high","mode":"steer"])
let (_, steer) = request("turn/steer")
precondition(steer["expectedTurnId"] as? String == "turn-1" && steer["threadId"] as? String == id)
precondition(steer["model"] == nil && steer["effort"] == nil && steer["cwd"] == nil && steer["sandboxPolicy"] == nil)
precondition(client.ledger.submissions.last!.model == "model-a","next-turn selection must not change Steer model")
client.saveDraft("Already typing the next message")
reply("turn/steer",["turnId":"turn-1"])
precondition(client.draftText == "Already typing the next message" && client.turnID == "turn-1")
// Once the source/target was confirmed, the actual instruction button sends
// directly; a busy target gets a durable queue entry without another modal.
client.stage("Complete next work order",source:source,message:"message-2")
let direct = client.ledger.submissions.last!
precondition(client.handoffCandidate == nil && direct.mode == "queue" && direct.text == "Complete next work order")
precondition(client.turnID == "turn-1" && client.draftText == "Already typing the next message")
let directCount = client.ledger.submissions.count
client.stage("Complete next work order",source:source,message:"message-2")
precondition(client.ledger.submissions.count == directCount && client.handoffCandidate == nil,"direct handoff remains idempotent")
client.deleteQueue(direct.id)
client.stage("Other source",source:URL(string:"https://chatgpt.com/c/another-source")!,message:"other-1")
precondition(client.handoffCandidate != nil && client.ledger.submissions.count == directCount,"another discussion cannot inherit the target confirmation")
client.handoffCandidate = nil
// Attachments carry actual content and are bounded to the input snapshot.
client.importAttachment(name:"note.md",mime:"text/plain",base64:Data("NON_SENSITIVE_ATTACHMENT".utf8).base64EncodedString())
client.stage("Review pending attachments",source:source,message:"message-3")
precondition(client.handoffCandidate != nil && client.ledger.submissions.count == directCount,"unsent composer attachments require explicit review")
client.handoffCandidate = nil
client.saveDraft("After completion, check existing features only")
client.submitComposer(["text":client.draftText,"model":"model-b","effort":"high","mode":"queue"])
var queued = client.ledger.submissions.last!
precondition(queued.state == "queued" && queued.attachments.count == 1)
let attachmentText=queued.input.last?["text"] as! String
precondition(attachmentText.hasPrefix("Text attachment supplied inline: note.md\n"))
precondition(attachmentText.contains(queued.attachments[0].sha256) && attachmentText.contains("not copied into the task folder"))
precondition(attachmentText.components(separatedBy:"--- BEGIN ATTACHMENT CONTENT ---\n").last == "NON_SENSITIVE_ATTACHMENT")
let legacyAttachment=CodexAttachment(id:"legacy",name:"note.md",mime:"text/plain",base64:Data("legacy bytes".utf8).base64EncodedString())
precondition((legacyAttachment.input["text"] as? String)?.hasPrefix("Attached file: note.md (SHA256 ") == true,"old receipts keep their wire format")
let savedAttachment=try JSONDecoder().decode(CodexAttachment.self,from:JSONEncoder().encode(queued.attachments[0]))
precondition(savedAttachment.transportVersion == 2 && savedAttachment.input["text"] as? String == attachmentText)
precondition(!client.requestMethods.values.contains("thread/queue/add"),"later inputs must not be auto-consumed after failed turns")
client.editQueue(["id":queued.id,"text":"Edited follow-up: verify existing functions"])
precondition(client.ledger.submissions.last!.text.hasPrefix("Edited") && client.ledger.submissions.last!.supersedes == queued.id)
queued = client.ledger.submissions.last!
client.submitComposer(["text":"Delete this queued item","model":"model-b","effort":"high","mode":"queue"])
let deleted = client.ledger.submissions.last!.id;client.deleteQueue(deleted)
precondition(client.ledger.submissions.last!.state == "cancelled" && client.turnID == "turn-1")
// A terminal race does not turn a failed Steer into a fresh turn.
client.saveDraft("Race input retained")
client.submitComposer(["text":client.draftText,"model":"model-b","effort":"high","mode":"steer"])
reject("turn/steer","expected turn is no longer active")
precondition(client.draftText == "Race input retained" && client.ledger.submissions.last!.state == "rejected")
precondition(!client.requestMethods.values.contains("turn/interrupt"))
event("item/completed",["threadId":id,"turnId":"turn-1","item":["id":"answer","type":"agentMessage","phase":"final_answer","text":"Actual fixture result"]])
event("turn/completed",["threadId":id,"turn":["id":"turn-1","status":"completed"]])
precondition(!client.isBusy && client.ledger.submissions[0].result == "Actual fixture result")
client.dispatchNext()
precondition(client.activeSubmission == queued.id)
reply("thread/settings/update",[:])
reply("thread/read",["thread":["id":id,"cwd":workspace.path,"historyMode":"paginated","environments":[["environmentId":"local","cwd":workspace.path,"runtimeWorkspaceRoots":[workspace.path]]],"model":"model-b","reasoningEffort":"high","status":["type":"idle"]]])
reply("thread/queue/list", ["data":[]])
let (_, next) = request("thread/queue/add")
precondition(next["clientUserMessageId"] as? String == queued.id)
event("turn/started",["threadId":id,"turn":["id":"turn-2"]])
event("item/started",["threadId":id,"turnId":"turn-2","item":["id":"user-2","type":"userMessage","clientId":queued.id,"content":[]]])
// Completion before the add acknowledgement must not resurrect work.
event("turn/completed",["threadId":id,"turn":["id":"turn-2","status":"failed","error":["message":"fixture failure"]]])
reply("thread/queue/add",["queuedSubmission":["id":"queue-2","clientUserMessageId":queued.id]])
precondition(!client.isBusy && client.ledger.paused.contains(id) && client.ledger.submissions.first(where:{$0.id==queued.id})!.state == "failed")
let count = client.requestID;client.dispatchNext();precondition(client.requestID == count)
// Scope identity cannot be replaced with a symlink to another folder.
let replaced = root.appendingPathComponent("preserved-workspace")
try FileManager.default.moveItem(at:workspace,to:replaced)
try FileManager.default.createSymbolicLink(at:workspace,withDestinationURL:root)
precondition(!client.validBinding(client.ledger.bindings[id]!))
try FileManager.default.removeItem(at:workspace)
try FileManager.default.moveItem(at:replaced,to:workspace)
// Unknown receipt requires exact client-id evidence, not just a newer turn.
client.changeSubmission(handoff.id) { $0.state="unknown"; $0.turn=nil }
client.uncertain=true
client.reconcileSavedInputs([["id":"unrelated","status":"completed","items":[]]])
precondition(client.uncertain)
client.reconcileSavedInputs([["id":"turn-1","status":"completed","completedAt":10,"items":[["id":"user","type":"userMessage","clientId":handoff.id,"content":[]],["id":"answer","type":"agentMessage","text":"Recovered result"]]]])
precondition(client.ledger.submissions[0].state == "completed")
// Restart restores bindings, drafts and queue safety without sending requests.
let restart = NativeCodex(resources:resources,preferences:root.appendingPathComponent("prefs"),translate:{$0})
precondition(restart.requestID == 0 && restart.ledger.bindings[id]!.directory == directory)
precondition(restart.ledger.handoffTargets?[source.absoluteString]?.directory == directory)
precondition(restart.ledger.submissions.filter({$0.id==handoff.id}).count == 1)
// Only published reasoning summaries cross into the renderer.
event("item/completed",["threadId":id,"item":["id":"reason","type":"reasoning","summary":["Published summary"],"content":["RAW_NOT_FOR_DISPLAY"]]])
let visible=String(data:try JSONSerialization.data(withJSONObject:client.pendingUI),encoding:.utf8)!
precondition(visible.contains("Published summary") && !visible.contains("RAW_NOT_FOR_DISPLAY"))

// Workspace-handoff repair: adversarial scope and delivery fixtures, no model.
func probe(_ name: String, controlled: Bool = false) {
    client = NativeCodex(resources:resources,preferences:root.appendingPathComponent(name),translate:{$0})
    client.connected=true;client.historyReady=true;client.ownerDesktopRunning={true}
    client.modelCatalog=[["model":"model-a","inputModalities":["text"],"supportedReasoningEfforts":[["reasoningEffort":"low"]]]]
    client.modelIDs=["model-a"];client.nextModel="model-a";client.nextEffort="low"
    client.selected=["id":id,"cwd":workspace.path]
    client.ledger.bindings[id]=CodexBinding(thread:id,directory:directory,permission:"twos-integrated",createdAt:1)
    if controlled {client.controlledThreads.insert(id)}
}
func verifiedThread(_ path: String = workspace.path) -> [String:Any] {
    ["id":id,"cwd":path,"historyMode":"paginated","environments":[["environmentId":"local","cwd":path,"runtimeWorkspaceRoots":[path]]],"model":"model-a","reasoningEffort":"low","status":["type":"idle"]]
}
// A new explicit handoff after Stop must start when no retained input remains.
// The same action must not silently authorize older queued or unknown work.
probe("fresh-after-stop",controlled:true)
client.ledger.paused.insert(id)
client.stage("Fresh instruction after an old Stop",source:source,message:"fresh-after-stop")
client.confirmHandoff(model:"model-a",effort:"low",hash:client.handoffCandidate!.hash)
precondition(!client.ledger.paused.contains(id) && client.ledger.submissions.count == 1)
precondition(client.requestMethods.values.contains("thread/settings/update"),"explicit handoff starts scope verification instead of silently sitting in an empty paused queue")
probe("preserve-paused-work",controlled:true)
var retained=handoff;retained.state="queued";client.ledger.submissions=[retained];client.ledger.paused.insert(id)
client.stage("Do not implicitly resume an older queue",source:source,message:"paused-existing")
client.confirmHandoff(model:"model-a",effort:"low",hash:client.handoffCandidate!.hash)
precondition(client.ledger.paused.contains(id) && client.requestID == 0 && client.ledger.submissions.count == 2)
probe("preserve-unknown-work",controlled:true)
retained.state="unknown";client.ledger.submissions=[retained];client.ledger.paused.insert(id)
let fresh=CodexSubmission(id:"unknown-guard",thread:id,directory:directory,text:"New",attachments:[],model:"model-a",effort:"low",mode:"send",createdAt:2,source:nil,message:nil,instructionHash:nil,state:"queued")
precondition(client.acceptSubmission(fresh) && client.ledger.paused.contains(id),"unreconciled input cannot be cleared by a new send")
probe("scope-conflict")
var control: Bool? = nil
client.ensureControl {control=$0}
reply("thread/read",["thread":verifiedThread(root.path)])
precondition(control == false && !client.requestMethods.values.contains("thread/resume"),"must not rewrite B to A during resume")
precondition(client.ledger.submissions.isEmpty)
probe("resume-valid")
client.ensureControl {control=$0}
var unloaded=verifiedThread();unloaded["environments"]=NSNull();unloaded["status"]=["type":"notLoaded"]
reply("thread/read",["thread":unloaded])
precondition(request("thread/resume").1["cwd"] as? String == workspace.path)
var resumed=verifiedThread();resumed["canAcceptDirectInput"]=true
reply("thread/resume",["thread":resumed,"cwd":workspace.path,"runtimeWorkspaceRoots":[workspace.path],"activePermissionProfile":["id":"twos-integrated"]])
precondition(control == true)
probe("changed-cwd",controlled:true)
client.submitComposer(["text":"No explicit path in business instruction","model":"model-a","effort":"low"])
reply("thread/settings/update",[:]);reply("thread/read",["thread":verifiedThread(root.path)])
precondition(!client.requestMethods.values.contains("thread/queue/add") && client.ledger.paused.contains(id))
precondition(client.ledger.submissions[0].dispatchContext == nil)
probe("changed-identity",controlled:true)
client.submitComposer(["text":"Check identity again after async response","model":"model-a","effort":"low"])
reply("thread/settings/update",[:]);reply("thread/read",["thread":verifiedThread()])
try FileManager.default.moveItem(at:workspace,to:replaced)
try FileManager.default.createDirectory(at:workspace,withIntermediateDirectories:false)
reply("thread/queue/list",["data":[]])
precondition(!client.requestMethods.values.contains("thread/queue/add") && client.ledger.paused.contains(id))
try FileManager.default.removeItem(at:workspace);try FileManager.default.moveItem(at:replaced,to:workspace)
probe("missing-binding",controlled:true)
client.ledger.bindings.removeValue(forKey:id)
client.submitComposer(["text":"Preserve draft","model":"model-a","effort":"low"])
precondition(client.requestID == 0 && client.ledger.submissions.isEmpty)
// Historical transport completed is not business success. Only an explicit
// click creates one associated new attempt, with the valid target reused.
probe("blocked-retry",controlled:true)
var blocked=handoff;blocked.state="completed";blocked.result="TASK_NAME: TEST\nRESULT: BLOCKED\n原因：没有收到目录上下文。";blocked.returnState="confirmed"
client.ledger.submissions=[blocked];client.ledger.paused.insert(id);client.persistLedger()
precondition(blocked.businessBlocked && blocked.businessResult == "blocked")
client.retryHandoff(blocked.id,source:URL(string:"https://chatgpt.com/c/other")!)
precondition(client.ledger.submissions.count == 1)
client.retryHandoff(blocked.id,source:source);client.retryHandoff(blocked.id,source:source)
precondition(client.ledger.submissions.count == 2 && client.ledger.submissions[0].result == blocked.result)
let attempt=client.ledger.submissions[1]
precondition(attempt.retryOf == blocked.id && attempt.id != blocked.id && attempt.directory == blocked.directory && attempt.text == blocked.text)
reply("thread/settings/update",[:]);reply("thread/read",["thread":verifiedThread()]);reply("thread/queue/list",["data":[]])
let retryInput=request("thread/queue/add").1["input"] as! [[String:Any]]
precondition((retryInput[0]["text"] as! String).contains(blocked.id) && (retryInput[0]["text"] as! String).contains(attempt.id))
// Lost receipt is reconciled by client ID, never retried on reconnect.
reply("thread/queue/add",[:]);precondition(client.uncertain)
client.retryHandoff(blocked.id,source:source);precondition(client.ledger.submissions.count == 2)
client.reconcileSavedInputs([["id":"retry-turn","status":"completed","completedAt":10,"items":[["id":"retry-user","type":"userMessage","clientId":attempt.id],["id":"retry-final","type":"agentMessage","text":"RESULT: PASS\nSynthetic result only"]]]])
precondition(client.ledger.submissions[1].businessResult == "reported_pass","model PASS is not verified success")
let recovered=NativeCodex(resources:resources,preferences:root.appendingPathComponent("blocked-retry"),translate:{$0})
precondition(recovered.requestID == 0 && recovered.ledger.submissions.count == 2)
precondition(recovered.ledger.submissions[0].businessResult == "blocked" && recovered.ledger.submissions[1].retryOf == blocked.id)


// Core client parity: actual production request routing, no inference.
probe("parity-requests",controlled:true)
client.turnID="parity-turn";client.activeSubmission="parity-delivery"
func approvalRequest(_ requestID: Int, turn: String = "parity-turn", extra: [String:Any] = [:]) {
    var params:[String:Any]=["threadId":id,"turnId":turn,"itemId":"approval-item","command":"pwd","cwd":workspace.path,"availableDecisions":["accept","decline","cancel"]]
    for (k,v) in extra {params[k]=v}
    client.receive(try! JSONSerialization.data(withJSONObject:["id":requestID,"method":"item/commandExecution/requestApproval","params":params])+Data([10]))
}
approvalRequest(900);approvalRequest(900)
precondition(client.approvals.count == 1,"duplicate request renders once")
let key=client.approvals.keys.first!
client.answer(["key":key,"decision":"accept"])
precondition(client.answeredApprovals.contains(key) && client.approvals.count == 1,"wait for actual server resolution")
client.answer(["key":key,"decision":"decline"])
precondition(client.answeredApprovals.count == 1,"cannot reuse an answered approval")
event("serverRequest/resolved",["threadId":foreign,"requestId":900]);precondition(client.approvals.count == 1)
event("serverRequest/resolved",["threadId":id,"requestId":900]);precondition(client.approvals.isEmpty && client.answeredApprovals.isEmpty)
approvalRequest(901,turn:"expired-turn");precondition(client.approvals.isEmpty)
approvalRequest(902,extra:["additionalPermissions":["network":["enabled":true]]])
let denied=client.approvals.keys.first!
client.answer(["key":denied,"decision":"accept"]);precondition(!client.answeredApprovals.contains(denied),"cannot widen network scope")
client.answer(["key":denied,"decision":"decline"]);precondition(client.answeredApprovals.contains(denied))
event("item/completed",["threadId":id,"turnId":"parity-turn","item":["id":"approval-item","type":"commandExecution","status":"declined"]])
precondition(client.approvals.isEmpty)
approvalRequest(903,extra:["grantRoot":root.path])
let outsideKey=client.approvals.keys.first!
client.answer(["key":outsideKey,"decision":"accept"])
precondition(!client.answeredApprovals.contains(outsideKey),"cannot approve an outside grant root")
event("serverRequest/resolved",["threadId":id,"requestId":903])
client.interrupt();let stopCount=client.requestID
precondition(client.stopRequested && client.isBusy)
client.interrupt();precondition(client.requestID == stopCount)
reply("turn/interrupt",[:]);precondition(client.stopRequested && client.isBusy,"stop acknowledgement is not terminal")
event("turn/completed",["threadId":id,"turn":["id":"parity-turn","status":"interrupted"]])
precondition(!client.stopRequested && !client.isBusy)
client.rememberDisplayEvent("item/started",["item":["id":"cmd","type":"commandExecution","command":"check","cwd":workspace.path]])
client.rememberDisplayEvent("item/commandExecution/outputDelta",["itemId":"cmd","delta":"Actual output"])
client.rememberDisplayEvent("item/reasoning/summaryTextDelta",["itemId":"reason","summaryIndex":2,"delta":"Public fragment"])
precondition(client.displayItems["cmd"]?["aggregatedOutput"] as? String == "Actual output")
precondition((client.displayItems["reason"]?["summary"] as? [String])?.last == "Public fragment")
client.rememberDisplayItem(["id":"reason","type":"reasoning","summary":["Public only"],"content":["SECRET_INTERNAL_REASONING"]])
client.publishDisplaySnapshot()
let publicDisplay = try JSONSerialization.data(withJSONObject:client.displayItems)
precondition(!String(data:publicDisplay,encoding:.utf8)!.contains("SECRET_INTERNAL_REASONING"))
// Product artifact actions require a real in-scope regular file, not model text.
let html = workspace.appendingPathComponent("index.html")
try Data("<!doctype html><script>window.untrusted=true</script>".utf8).write(to:html)
let read: (URL,Data)
do { read = try NativeCodex.readArtifact("index.html",directory:directory) } catch {
 var info=stat();let fd=Darwin.open(directory.path,O_RDONLY|O_DIRECTORY|O_NOFOLLOW);let fs=fstat(fd,&info);if fd>=0 {Darwin.close(fd)}
 fatalError("artifact read: \(error); directory=\(directory); real=\(URL(fileURLWithPath:directory.path).resolvingSymlinksInPath().path); fd=\(fd); fstat=\(fs) dev=\(info.st_dev) ino=\(info.st_ino); files=\((try? FileManager.default.contentsOfDirectory(atPath:workspace.path)) ?? [])")
}
precondition(read.0 == html && String(data:read.1,encoding:.utf8)!.contains("<script>"))
func refuses(_ path: String) {do {_ = try NativeCodex.readArtifact(path,directory:directory);fatalError("unsafe artifact accepted: \(path)")}catch{}}
refuses("../index.html");refuses(root.appendingPathComponent("outside.html").path);refuses(".codex/auth.json")
let external=root.appendingPathComponent("outside.html");try Data("outside".utf8).write(to:external)
let linked=workspace.appendingPathComponent("linked.html");try FileManager.default.createSymbolicLink(at:linked,withDestinationURL:external);refuses("linked.html")
let linkedDir=workspace.appendingPathComponent("linked-dir");try FileManager.default.createSymbolicLink(at:linkedDir,withDestinationURL:root);refuses("linked-dir/outside.html")
let hard=workspace.appendingPathComponent("hard.html");try FileManager.default.linkItem(at:external,to:hard);refuses("hard.html")
client.artifactAction(["threadId":foreign,"path":"index.html","operation":"view"])
precondition(!client.pendingUI.contains(where:{$0["kind"] as? String == "artifactContent"}))
client.artifactAction(["threadId":id,"path":"index.html","operation":"view"])
precondition(client.pendingUI.contains(where:{$0["kind"] as? String == "artifactContent"}),"HTML goes to plain text preview, not WebKit navigation")
precondition(client.requestID == stopCount,"file viewing does not call a model")

// Saving is a byte-for-byte native copy, including non-UTF8 data. It never
// changes the source, and a changed source/unsafe destination cannot clobber
// the previously exported copy. All inputs are non-sensitive fixtures.
let exports = root.appendingPathComponent("exports")
try FileManager.default.createDirectory(at:exports,withIntermediateDirectories:false)
for (name, bytes) in [("review.md",Data("# 工程样本\n中文正文\n".utf8)),
                      ("receipt.json",Data("{\"result\":\"fixture\"}\n".utf8)),
                      ("image.png",Data([0x89,0x50,0x4e,0x47,0,255]))] {
    let original=workspace.appendingPathComponent(name), destination=exports.appendingPathComponent(name)
    try bytes.write(to:original)
    try NativeCodex.saveArtifactCopy(name,directory:directory,expectedHash:NativeCodex.digest(bytes),to:destination)
    let copyBytes = try Data(contentsOf:destination), sourceBytes = try Data(contentsOf:original)
    precondition(copyBytes == bytes && sourceBytes == bytes)
    try Data("old destination".utf8).write(to:destination)
    try NativeCodex.saveArtifactCopy(name,directory:directory,expectedHash:NativeCodex.digest(bytes),to:destination)
    let overwritten = try Data(contentsOf:destination)
    precondition(overwritten == bytes,"confirmed overwrite keeps the exact bytes")
}
let report=workspace.appendingPathComponent("review.md"), exported=exports.appendingPathComponent("review.md")
let reportBytes=try Data(contentsOf:report), reportHash=NativeCodex.digest(reportBytes)
func refusesCopy(_ path:String = "review.md", _ destination:URL, hash:String? = nil, scope:CodexDirectory? = nil) {
    do {try NativeCodex.saveArtifactCopy(path,directory:scope ?? directory,expectedHash:hash ?? reportHash,to:destination);fatalError("unsafe copy accepted")}
    catch {}
}
refusesCopy("review.md",report)
let alternateCase=workspace.appendingPathComponent("REVIEW.MD")
if FileManager.default.fileExists(atPath:alternateCase.path) { refusesCopy("review.md",alternateCase) }
refusesCopy("../outside.html",exported)
refusesCopy("linked.html",exported)
refusesCopy("review.md",exported,hash:"old snapshot")
let badScope=CodexDirectory(path:directory.path,device:directory.device,inode:directory.inode+1,isolated:true)
refusesCopy("review.md",exported,scope:badScope)
let destinationLink=exports.appendingPathComponent("linked.md")
try FileManager.default.createSymbolicLink(at:destinationLink,withDestinationURL:report)
refusesCopy("review.md",destinationLink)
let directoryLink=root.appendingPathComponent("export-link")
try FileManager.default.createSymbolicLink(at:directoryLink,withDestinationURL:exports)
refusesCopy("review.md",directoryLink.appendingPathComponent("review.md"))
let targetFolder=exports.appendingPathComponent("folder.md")
try FileManager.default.createDirectory(at:targetFolder,withIntermediateDirectories:false)
refusesCopy("review.md",targetFolder)
let missingParent=root.appendingPathComponent("missing-directory")
refusesCopy("review.md",missingParent.appendingPathComponent("review.md"))
let preservedSource=try Data(contentsOf:report), preservedCopy=try Data(contentsOf:exported)
precondition(preservedSource == reportBytes && preservedCopy == reportBytes)
let exportedNames=try FileManager.default.contentsOfDirectory(atPath:exports.path)
precondition(!exportedNames.contains(where:{$0.hasPrefix(".twos-export-")}))
precondition(client.requestID == stopCount,"saving a copy never starts or modifies a model turn")

// Cold-resumed official queues can accept an input without starting a turn.
func acceptedColdInput(_ name: String) -> CodexSubmission {
    probe(name,controlled:true)
    client.submitComposer(["text":"Read-only cold resume check","model":"model-a","effort":"low"])
    reply("thread/settings/update",[:]);reply("thread/read",["thread":verifiedThread()]);reply("thread/queue/list",["data":[]])
    let record=client.ledger.submissions.last!
    reply("thread/queue/add",["queuedSubmission":["id":"saved-queue","clientUserMessageId":record.id]])
    return client.ledger.submissions.last!
}
func exactQueue(_ record: CodexSubmission) -> [String: Any] {
    ["id":"saved-queue","clientUserMessageId":record.id,"input":record.input]
}
var cold=acceptedColdInput("cold-queue-start")
precondition(cold.state == "accepted" && cold.turn == nil && client.startingTurn)
let pendingCount=client.requestID
client.startAcceptedQueue(cold.id);precondition(client.requestID == pendingCount,"double click cannot race a pending queue-start check")
client.saveDraft("Keep steer draft before real turn")
client.submitComposer(["text":client.draftText,"model":"model-a","effort":"low","mode":"steer"])
precondition(client.ledger.submissions.count == 1 && client.draftText.contains("Keep steer"),"accepted without a turn is not steerable")
reply("thread/read",["thread":verifiedThread()]);reply("thread/queue/list",["data":[exactQueue(cold)]])
let start=request("thread/queue/start").1
precondition(start["queuedSubmissionId"] as? String == "saved-queue" && start["threadId"] as? String == id)
event("turn/started",["threadId":id,"turn":["id":"cold-turn"]])
event("item/started",["threadId":id,"turnId":"cold-turn","item":["id":"cold-user","type":"userMessage","clientId":cold.id,"content":[]]])
reply("thread/queue/start",["turn":["id":"cold-turn","status":"inProgress"]])
precondition(client.turnID == "cold-turn" && client.ledger.submissions.count == 1 && !client.uncertain)

cold=acceptedColdInput("automatic-drain-race")
event("turn/started",["threadId":id,"turn":["id":"automatic-turn"]])
event("item/started",["threadId":id,"turnId":"automatic-turn","item":["id":"automatic-user","type":"userMessage","clientId":cold.id,"content":[]]])
reply("thread/read",["thread":verifiedThread()])
precondition(!client.requestMethods.values.contains("thread/queue/start") && client.turnID == "automatic-turn","automatic drain wins without a second start")

// thread/read can observe the automatic drain before its turn/started event.
// An active status is not evidence of another writer or permission to restart.
cold=acceptedColdInput("active-read-before-start-event")
var activeThread=verifiedThread();activeThread["status"]=["type":"active","activeFlags":[]]
reply("thread/read",["thread":activeThread])
precondition(client.startingTurn && client.activeSubmission == cold.id && !client.uncertain,
             "a scope-matched active read must retain the exact pending delivery while awaiting its start event")
precondition(!client.requestMethods.values.contains("thread/queue/start") && !client.requestMethods.values.contains("thread/queue/add"),
             "an automatic drain must never be duplicated")
event("turn/started",["threadId":id,"turn":["id":"late-start-turn"]])
event("item/started",["threadId":id,"turnId":"late-start-turn","item":["id":"late-start-user","type":"userMessage","clientId":cold.id,"content":[]]])
precondition(client.turnID == "late-start-turn" && client.activeSubmission == cold.id && !client.uncertain)
event("turn/completed",["threadId":id,"turn":["id":"late-start-turn","status":"completed"]])
precondition(client.ledger.submissions.count == 1 && client.ledger.submissions[0].state == "completed" && !client.ledger.paused.contains(id))

cold=acceptedColdInput("active-read-foreign-input")
reply("thread/read",["thread":activeThread])
event("turn/started",["threadId":id,"turn":["id":"foreign-active-turn"]])
event("item/started",["threadId":id,"turnId":"foreign-active-turn","item":["id":"foreign-user","type":"userMessage","clientId":"not-this-delivery","content":[]]])
precondition(client.uncertain && client.ledger.paused.contains(id) && client.ledger.submissions[0].turn == nil,
             "active status alone must not assign a different client's turn to our pending input")

for ordering in ["empty-queue-before-event", "start-rejection-before-event"] {
    cold=acceptedColdInput(ordering)
    reply("thread/read",["thread":verifiedThread()])
    if ordering == "empty-queue-before-event" {
        reply("thread/queue/list",["data":[]])
    } else {
        reply("thread/queue/list",["data":[exactQueue(cold)]])
        reject("thread/queue/start","Queued submission has already been consumed")
    }
    precondition(client.startingTurn && client.activeSubmission == cold.id && !client.uncertain,
                 "consumed queue metadata must wait for immutable client identity, not clear the pending delivery")
    let requestsBeforeStart=client.requestID
    event("turn/started",["threadId":id,"turn":["id":ordering]])
    event("item/started",["threadId":id,"turnId":ordering,"item":["id":"race-user","type":"userMessage","clientId":cold.id,"content":[]]])
    precondition(client.turnID == ordering && !client.uncertain && client.requestID == requestsBeforeStart)
    event("turn/completed",["threadId":id,"turn":["id":ordering,"status":"completed"]])
    precondition(client.ledger.submissions.count == 1 && client.ledger.submissions[0].state == "completed" && !client.ledger.paused.contains(id))
}

for invalid in ["extra-entry","changed-input","changed-folder","changed-model"] {
    cold=acceptedColdInput(invalid)
    var thread=verifiedThread();if invalid == "changed-folder" {thread["cwd"]=root.path};if invalid == "changed-model" {thread["model"]="other"}
    reply("thread/read",["thread":thread])
    if invalid == "extra-entry" {reply("thread/queue/list",["data":[exactQueue(cold),["id":"foreign","clientUserMessageId":"foreign","input":[]]]])}
    if invalid == "changed-input" {var changed=exactQueue(cold);changed["input"]=[["type":"text","text":"different task"]];reply("thread/queue/list",["data":[changed]])}
    precondition(client.uncertain && !client.isBusy && !client.requestMethods.values.contains("thread/queue/start"),"invalid saved scope/input must not start")
}
cold=acceptedColdInput("lost-start-receipt")
reply("thread/read",["thread":verifiedThread()]);reply("thread/queue/list",["data":[exactQueue(cold)]])
reply("thread/queue/start",[:])
precondition(client.uncertain && !client.isBusy && client.ledger.submissions.last!.state == "unknown")
let afterUnknown=client.requestID
client.dispatchNext();precondition(client.requestID == afterUnknown,"unknown receipt never adds another message")
client.startAcceptedQueue(cold.id,recovering:true)
reply("thread/read",["thread":verifiedThread()]);reply("thread/queue/list",["data":[exactQueue(cold)]])
precondition(request("thread/queue/start").1["queuedSubmissionId"] as? String == "saved-queue" && client.ledger.submissions.count == 1,"explicit recovery revalidates and uses the same stored queue ID")
reply("thread/queue/start",["turn":["id":"recovered-queue-turn","status":"inProgress"]])
precondition(!client.uncertain && client.turnID == "recovered-queue-turn")

// Unloaded official readers can label a still-active turn interrupted without
// a completion timestamp. Neither history projection may clear pending input,
// publish a terminal business result, or make a queued task eligible to run.
probe("unloaded-active-history")
var observed=CodexSubmission(id:"observed-client",thread:id,directory:directory,text:"Original input",attachments:[],model:"model-a",effort:"low",mode:"send",createdAt:1,source:source.absoluteString,message:"observed-message",instructionHash:"hash",state:"unknown")
observed.turn="observed-turn";client.ledger.submissions=[observed];client.markPending("observed-turn");client.uncertain=true
let observedItems:[[String:Any]]=[["id":"observed-user","type":"userMessage","clientId":observed.id],["id":"unfinished-answer","type":"agentMessage","text":"Not a terminal result"]]
var projected:[String:Any]=["id":"observed-turn","status":"interrupted","startedAt":100,"completedAt":NSNull(),"items":observedItems]
client.loadHistory(older:false);reply("thread/turns/list",["data":[projected]])
precondition(client.uncertain && client.readMap("codex-pending.json")[id] == "observed-turn")
precondition(client.ledger.submissions[0].state == "unknown" && client.ledger.submissions[0].result == nil)
let blockedRequests=client.requestID;client.dispatchNext();precondition(client.requestID == blockedRequests)
projected["status"]="completed";client.reconcileSavedInputs([projected])
precondition(client.ledger.submissions[0].state == "unknown" && client.lastResult.isEmpty,"terminal label without completion evidence is not enough")
projected["completedAt"]=90;precondition(client.confirmedHistoryTerminal(projected) == nil,"completion cannot precede start")
projected["completedAt"]=110
client.loadHistory(older:false);reply("thread/turns/list",["data":[projected]])
precondition(client.ledger.submissions[0].state == "completed" && !client.uncertain && client.readMap("codex-pending.json")[id] == nil)
client.completedTurns.insert("observed-turn");projected["status"]="interrupted";projected["completedAt"]=NSNull()
client.reconcileSavedInputs([projected])
precondition(client.ledger.submissions[0].state == "completed","stale observer projection cannot reverse a live terminal event")

print("NATIVE_CONTEXT_STATE_PASS")
exit(0)
'''
    source=root/'main.swift';source.write_text(production+harness)
    binary=root/'native-client'
    compiled=subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(root/'cache'),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120)
    assert compiled.returncode==0,compiled.stderr
    return binary


def test_native_context_identity_restart_duplicate_and_origin_boundaries(native_client,tmp_path):
    ran=subprocess.run([str(native_client),str(tmp_path/'case'),str(ROOT/'static_cockpit')],capture_output=True,text=True,timeout=45)
    assert ran.returncode==0,ran.stderr
    assert 'NATIVE_CONTEXT_STATE_PASS' in ran.stdout
