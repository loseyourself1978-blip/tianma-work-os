"""SIMULATED provider pages in real WebKit. No provider account/model is used."""
from pathlib import Path
import subprocess, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import pytest

ROOT=Path(__file__).resolve().parents[1]
pytestmark=pytest.mark.skipif(sys.platform!='darwin',reason='macOS WebKit')

@pytest.fixture(scope='module')
def cross_harness(tmp_path_factory):
    root=tmp_path_factory.mktemp('cross-provider-harness')
    code=(ROOT/'packaging/macos/TianmaLauncher.swift').read_text().split('// The only child runtime',1)[0]
    for name in ('CodexAttachments.swift','CodexTelemetry.swift','NativeCodex.swift','IntegratedWorkbench.swift','PairedWorkflow.swift'):
        code+='\n'+(ROOT/'packaging/macos'/name).read_text()
    # Fixture-only target/process lookup: exercise the production refresh and
    # asynchronous read path with a selected standalone and no bundled helper.
    # No production trust check is bypassed outside this compiled test harness.
    code=code.replace('var targetURL: URL? { standalone?.bundleURL ?? helperURL }',
        'var targetURL: URL? { CommandLine.arguments[1] == "nyra_selected_target" ? Bundle.main.bundleURL : (standalone?.bundleURL ?? helperURL) }')
    code=code.replace('var targetStateRoot: URL {\n        standalone != nil ?',
        'var targetStateRoot: URL {\n        if CommandLine.arguments[1] == "nyra_selected_target" { return stateRoot }; return standalone != nil ?')
    code=code.replace('var targetProcesses: [NSRunningApplication] {\n        if let app = standalone',
        'var targetProcesses: [NSRunningApplication] {\n        if CommandLine.arguments[1] == "nyra_selected_target" { return [.current] }; if let app = standalone')
    # The real R4 consumer and decoder, without the companion UI extension.
    code+='\n'+(ROOT/'packaging/macos/nyra/Sources/ReactiveState.swift').read_text().split('struct ReactiveState {',1)[0]
    code+='\nenum PreviewError: Error { case invalidManifest }\n'
    code+='\n'+(ROOT/'packaging/macos/nyra/Sources/NyraStatusClient.swift').read_text().split('extension Companion {',1)[0]
    code+=r'''
let app=NSApplication.shared
let mode=CommandLine.arguments[1], prefs=URL(fileURLWithPath:CommandLine.arguments[2]), base=URL(string:CommandLine.arguments[3])!, resources=URL(fileURLWithPath:CommandLine.arguments[4])
if mode == "nyra_selection_async" {
    let client=NyraStatusClient();var callbacks=0;var loaders=0
    let gate=DispatchSemaphore(value:0)
    client.poll(selectionLoader:{
        dispatchPrecondition(condition:.notOnQueue(.main));loaders += 1
        precondition(gate.wait(timeout:.now()+2) == .success)
        throw BridgeError.unavailable
    }) {_ in callbacks += 1}
    client.poll(selectionLoader:{fatalError("duplicate pending loader")}) {_ in fatalError("duplicate callback")}
    DispatchQueue.main.asyncAfter(deadline:.now()+0.05){
        precondition(callbacks==0);client.stop();gate.signal()
    }
    DispatchQueue.main.asyncAfter(deadline:.now()+0.3){
        precondition(callbacks==0 && loaders==1,"stopped pending selection must not publish stale state")
        client.poll(selectionLoader:{throw BridgeError.unavailable}) {result in
            precondition(Thread.isMainThread)
            if case .success = result { fatalError("unavailable selection accepted") }
            print("NYRA_BACKGROUND_SELECTION_UI_RESPONSIVE_DEDUP_AND_CANCEL_PASS");exit(0)
        }
    }
    app.run();exit(0)
}
if mode == "owner_result_binding" {
    var record=CodexSubmission(id:"TEST-RESULT",thread:"TEST-THREAD",directory:CodexDirectory(path:prefs.path,device:0,inode:0,isolated:true),text:"TEST/FIXTURE",attachments:[],model:"fixture",effort:"low",mode:"send",createdAt:1,source:nil,message:nil,instructionHash:nil,state:"completed")
    record.turn="TEST-TURN";record.result="RESULT: PARTIAL\nTEST/FIXTURE result"
    let original=try! JSONEncoder().encode(record)
    precondition(try! JSONDecoder().decode(CodexSubmission.self,from:original).validOwnerResultCheck == nil)
    record.ownerResultCheck=CodexOwnerResultCheck(id:UUID().uuidString,turn:"TEST-TURN",resultHash:NativeCodex.digest(Data(record.result!.utf8)),recordedAt:2)
    precondition(record.validOwnerResultCheck != nil && record.businessResult == "partial","scoped human check must preserve executor PARTIAL")
    let checked=record
    record.turn="OTHER-TURN";precondition(record.validOwnerResultCheck == nil)
    record=checked;record.result="Changed result";precondition(record.validOwnerResultCheck == nil)
    record=checked;record.state="failed";precondition(record.validOwnerResultCheck == nil)
    record=checked;record.ownerResultCheck=CodexOwnerResultCheck(id:"",turn:"TEST-TURN",resultHash:NativeCodex.digest(Data(record.result!.utf8)),recordedAt:2)
    precondition(record.validOwnerResultCheck == nil)
    print("RESULT_CHECK_IDENTITY_HASH_TERMINAL_AND_ORIGINAL_REPORT_PASS");exit(0)
}
if mode == "status_server" {
    let producer=NyraStatusProducer(directory:prefs.appendingPathComponent("status"),helper:prefs.appendingPathComponent("Allowed.app"))
    precondition(producer.endpointError == nil)
    producer.observe(session:"TEST-SESSION",task:"TEST-TASK",state:"completed_unverified",source:"codex_adapter")
    try! Data("ready".utf8).write(to:prefs.appendingPathComponent("ready"))
    DispatchQueue.main.asyncAfter(deadline:.now()+25){ withExtendedLifetime(producer) {};exit(0) };app.run();exit(0)
}
if mode == "status_client" || mode == "status_client_abandon" {
    let d=try! Data(contentsOf:prefs.appendingPathComponent("status/endpoint.json"))
    let endpoint=try! JSONSerialization.jsonObject(with:d) as! [String:Any]
    let path=endpoint["socket"] as! String
    let fd=Darwin.socket(AF_UNIX,SOCK_STREAM,0);var address=sockaddr_un();address.sun_family=sa_family_t(AF_UNIX);address.sun_len=UInt8(MemoryLayout<sockaddr_un>.size)
    withUnsafeMutableBytes(of:&address.sun_path){bytes in path.utf8CString.withUnsafeBytes{bytes.copyMemory(from:$0)}}
    let connected=withUnsafePointer(to:&address){p in p.withMemoryRebound(to:sockaddr.self,capacity:1){Darwin.connect(fd,$0,socklen_t(MemoryLayout<sockaddr_un>.size))}}
    precondition(connected==0)
    if mode == "status_client_abandon" {
        // Keep the authenticated helper process alive, but close its stream
        // before the host accepts it (the Python test pauses only its fixture).
        Darwin.close(fd); Thread.sleep(forTimeInterval:2); print("CLIENT_CLOSED"); exit(0)
    }
    var bytes=[UInt8](repeating:0,count:2048);let count=Darwin.read(fd,&bytes,bytes.count);Darwin.close(fd)
    print(count > 0 ? String(data:Data(bytes.prefix(count)),encoding:.utf8)!:"DENIED");exit(0)
}
if mode == "status_client_strict" {
    let producer=URL(fileURLWithPath:CommandLine.arguments[4])
    do {
        let selection=BridgeSelection(endpoint:prefs.appendingPathComponent("status/endpoint.json").path,
            producerApp:producer.path,producerBundleID:Bundle(url:producer)!.bundleIdentifier!,producerCodeHash:try NyraStatusClient.codeHash(producer))
        let event=try NyraStatusClient.read(selection)
        precondition(event.state == .completed_unverified && !event.simulation && event.task_id == "TEST-TASK")
        var reducer=StatusReducer();let first=reducer.receive(event,now:100);let again=reducer.receive(event,now:102)
        precondition(first.accepted && again.accepted && !first.celebrate && !again.celebrate)
        precondition(reducer.celebrationCount==0)
        print("STRICT_R4_READONLY_PEER_AND_DEDUP_PASS")
    } catch { print("STRICT_R4_DENIED: \(error)") }
    exit(0)
}
if mode == "nyra_socket_queue" {
    let producer=NyraStatusProducer(directory:prefs.appendingPathComponent("status"),helper:prefs.appendingPathComponent("Missing.app"))
    let gate=DispatchSemaphore(value:0), entered=DispatchSemaphore(value:0)
    producer.socketQueue.async {
        dispatchPrecondition(condition:.notOnQueue(.main))
        entered.signal()
        precondition(gate.wait(timeout:.now()+3) == .success)
    }
    precondition(entered.wait(timeout:.now()+1) == .success)
    DispatchQueue.main.asyncAfter(deadline:.now()+0.1) {
        producer.observe(session:"TEST-QUEUE",task:"TEST-TASK",state:"running",source:"twos_runtime")
        producer.snapshot { bytes in
            let state=try! JSONSerialization.jsonObject(with:bytes) as! [String:Any]
            precondition(state["state"] as? String == "running")
            gate.signal()
            producer.socketQueue.async {
                DispatchQueue.main.async {
                    withExtendedLifetime(producer) {}
                    print("NYRA_SERIAL_PEER_WAIT_DOES_NOT_BLOCK_UI_OR_STATE_PASS");exit(0)
                }
            }
        }
    }
    app.run();exit(0)
}
if mode == "nyra_selected_target" {
    var reads=0, observed=false
    let bridge=NativeNyra(stateRoot:prefs) { state in
        if state["observed"] as? Bool == true && state["visible"] as? Bool == true { observed=true }
    }
    precondition(bridge.helperURL == nil && bridge.targetURL == Bundle.main.bundleURL)
    bridge.visibilityReader={file in
        dispatchPrecondition(condition:.notOnQueue(.main))
        precondition(file == prefs.appendingPathComponent("visibility-state.json"))
        reads += 1
        return ["pid":ProcessInfo.processInfo.processIdentifier,"bundle":Bundle.main.bundleURL.path,"visible":true]
    }
    bridge.refresh()
    DispatchQueue.main.asyncAfter(deadline:.now()+0.4) {
        precondition(reads == 1 && observed,"selected standalone never became observable")
        precondition(bridge.snapshot()["visible"] as? Bool == true)
        precondition(bridge.snapshot()["binding"] as? String == "NOT_CONNECTED","showing standalone does not claim task binding")
        withExtendedLifetime(bridge) {}
        print("NYRA_SELECTED_STANDALONE_REFRESH_PASS");exit(0)
    }
    app.run();exit(0)
}
if mode == "nyra_file_wait" {
    try! NativeWorkbench.safeDirectory(prefs)
    let nyra=NativeNyra(stateRoot:prefs,changed:{_ in})
    let gate=DispatchSemaphore(value:0), lock=NSLock()
    var reads=0
    nyra.visibilityReader={_ in
        lock.lock();reads += 1;let first=reads==1;lock.unlock()
        if first { precondition(gate.wait(timeout:.now()+4) == .success) }
        return nil
    }
    nyra.requestVisibilityRead();nyra.requestVisibilityRead()
    precondition(nyra.stateReadInFlight)
    DispatchQueue.main.asyncAfter(deadline:.now()+0.1) {
        precondition(nyra.stateReadInFlight,"blocked file read must not block the main queue")
        gate.signal()
    }
    DispatchQueue.main.asyncAfter(deadline:.now()+0.8) {
        lock.lock();let count=reads;lock.unlock()
        precondition(count==2 && !nyra.stateReadInFlight,"coalesced refresh must settle")
        let file=prefs.appendingPathComponent("visibility-state.json")
        try! Data("{\"visible\":true}".utf8).write(to:file)
        precondition(NativeNyra.readVisibility(file)?["visible"] as? Bool == true)
        let link=prefs.appendingPathComponent("link")
        try! FileManager.default.createSymbolicLink(at:link,withDestinationURL:file)
        precondition(NativeNyra.readVisibility(link)==nil)
        let fifo=prefs.appendingPathComponent("fifo");precondition(mkfifo(fifo.path,0o600)==0)
        precondition(NativeNyra.readVisibility(fifo)==nil)
        print("NYRA_PERMISSION_WAIT_MAIN_QUEUE_AND_BOUNDED_READ_PASS");exit(0)
    }
    app.run();exit(0)
}
if mode == "nyra_status" {
    let producer=NyraStatusProducer(directory:prefs.appendingPathComponent("status"),helper:prefs.appendingPathComponent("Missing.app"))
    precondition(producer.endpointError == nil)
    precondition((try! FileManager.default.attributesOfItem(atPath:prefs.appendingPathComponent("status/endpoint.json").path))[.posixPermissions] as? Int == 0o600)
    func snapshot(_ p:NyraStatusProducer)->[String:Any] {
        var answer:[String:Any]?
        p.snapshot { answer=try! JSONSerialization.jsonObject(with:$0) as? [String:Any] }
        while answer == nil { RunLoop.current.run(until:Date().addingTimeInterval(0.01)) }
        return answer!
    }
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"running",source:"codex_adapter")
    let a=snapshot(producer)
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"running",source:"codex_adapter")
    let duplicate=snapshot(producer)
    precondition(a["event_id"] as? String == duplicate["event_id"] as? String && a["sequence"] as? Int == duplicate["sequence"] as? Int)
    producer.observe(session:"/private/path",task:"TASK-1",state:"running",source:"codex_adapter")
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"verified_success",source:"codex_adapter")
    precondition(snapshot(producer)["event_id"] as? String == a["event_id"] as? String)
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"waiting_user",source:"codex_adapter")
    precondition(snapshot(producer)["state"] as? String == "waiting_user")
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"disconnected",source:"codex_adapter")
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"running",source:"codex_adapter")
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"completed_unverified",source:"codex_adapter")
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"running",source:"codex_adapter")
    let final=snapshot(producer);precondition(final["state"] as? String == "completed_unverified")
    precondition(Set(final.keys)==Set(["schema_version","producer_instance_id","event_id","sequence","timestamp","session_id","task_id","state","source","simulation"]))
    precondition(final["simulation"] as? Bool == false)
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"verified_success",source:"twos_runtime")
    precondition(snapshot(producer)["state"] as? String == "completed_unverified")
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"verified_success",source:"web_handoff_adapter",ownerEvidence:"CHECK-1")
    precondition(snapshot(producer)["state"] as? String == "completed_unverified")
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"verified_success",source:"twos_runtime",ownerEvidence:"CHECK-1")
    let checked=snapshot(producer)
    precondition(checked["state"] as? String == "verified_success" && checked["evidence_ref"] as? String == "CHECK-1")
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"running",source:"codex_adapter")
    producer.observe(session:"SESSION-A",task:"TASK-1",state:"completed_unverified",source:"codex_adapter")
    precondition(snapshot(producer)["event_id"] as? String == checked["event_id"] as? String)
    var run=CodexRunObservation(thread:"T",turn:"R",lastActivity:1);run.state="completed"
    for business in ["reported_pass","unverified"] { precondition(NyraStatusProducer.codexState(run:run,online:true,business:business)=="completed_unverified") }
    precondition(NyraStatusProducer.codexState(run:run,online:true,business:"partial")=="partial")
    precondition(NyraStatusProducer.webState("reply")=="completed_unverified")
    precondition(NyraStatusProducer.webState("sent")=="disconnected") // durable history is not live work
    precondition(NyraStatusProducer.webState("sent",observed:"sent",fresh:true)=="running")
    precondition(NyraStatusProducer.webState("sent",observed:"unknown",fresh:true)=="disconnected")
    precondition(NyraStatusProducer.webState("sent",observed:"sent",fresh:false)=="disconnected")
    precondition(NyraStatusProducer.webState("reply",observed:"unknown",fresh:false)=="completed_unverified")
    producer.observe(session:"SESSION-B",task:"TASK-2",state:"queued",source:"web_handoff_adapter")
    precondition(snapshot(producer)["state"] as? String == "queued")
    let restarted=NyraStatusProducer(directory:prefs.appendingPathComponent("restarted"),helper:prefs.appendingPathComponent("Missing.app"))
    precondition(restarted.instance != producer.instance && snapshot(restarted)["state"] as? String == "idle")
    let link=prefs.appendingPathComponent("link");try! FileManager.default.createSymbolicLink(at:link,withDestinationURL:prefs)
    let rejected=NyraStatusProducer(directory:link.appendingPathComponent("no-write"),helper:prefs.appendingPathComponent("Missing.app"))
    precondition(rejected.endpointError != nil)
    producer.observe(session:"BOTH-PANES",task:nil,state:"running",source:"twos_runtime",side:"left")
    let both=snapshot(producer)
    precondition(both["schema_version"] as? String == "twos.nyra.status.v2")
    precondition(Set(both.keys)==Set(["schema_version","producer_instance_id","event_id","sequence","timestamp","session_id","task_id","state","source","simulation","activity_side"]))
    let decoded=try! StatusEvent.decode(JSONSerialization.data(withJSONObject:both),simulation:false)
    precondition(decoded.activity_side=="left")
    producer.observe(session:"BOTH-PANES",task:nil,state:"running",source:"twos_runtime",side:"/private/path")
    precondition(snapshot(producer)["event_id"] as? String==both["event_id"] as? String)
    print("NYRA_STATUS_PRIVACY_DEDUP_RECONNECT_TERMINAL_PASS");exit(0)
}

if mode == "paired_policy" {
    let now=ProcessInfo.processInfo.systemUptime
    func a(_ state:String,_ age:Double=0)->PaneActivity { PaneActivity(session:"opaque",task:nil,state:state,at:now-age) }
    precondition(PaneActivity.aggregate([0:a("running"),1:a("idle")]).side=="left")
    precondition(PaneActivity.aggregate([0:a("running"),1:a("running")]).side=="both")
    precondition(PaneActivity.aggregate([0:a("idle"),1:a("running")]).state=="running")
    precondition(PaneActivity.aggregate([0:a("idle"),1:a("idle")]).state=="idle")
    precondition(PaneActivity.aggregate([0:a("idle"),1:a("running",12)]).state=="disconnected")
    precondition(PaneActivity.aggregate([0:a("waiting_user"),1:a("idle")]).state=="waiting_user")
    for text in ["> 我认输。","```text\n我认输\n```","The old participant said 我认输。","Do not say I concede.","\"I concede.\""] {precondition(!PairedDialogue.concession(text))}
    precondition(PairedDialogue.concession("A complete answer.\nI concede."))
    precondition(PairedDialogue.concession("Completed response\nSTATUS: STALEMATE"))
    precondition(!PairedDialogue.concession("Quoted example:\n> STATUS: CONCEDE"))
    precondition(PaneActivity.aggregate([0:a("verified_success"),1:a("running")]).state=="running")
    precondition(PaneActivity.aggregate([0:a("verified_success"),1:a("partial")]).state=="partial")
    precondition(PaneActivity.aggregate([0:a("verified_success"),1:a("idle")]).state=="verified_success")
    let d=PairedDialogue(id:"FIXTURE",providers:["ChatGPT","Claude"],conversations:["https://chatgpt.com/c/f","https://claude.ai/chat/f"],roles:["a","b"],firstText:"non-sensitive",maxExchanges:6,duration:120,createdAt:1)
    let restored=try! JSONDecoder().decode(PairedDialogue.self,from:JSONEncoder().encode(d))
    precondition(restored.valid && restored.state=="paused" && restored.nextTarget==1 && restored.deadline==121)
    let saved=try! JSONSerialization.jsonObject(with:JSONEncoder().encode(d)) as! [String:Any]
    for (field,bad) in [("providers",[] as Any),("conversations",["one"] as Any),("roles",["one"] as Any),("maxExchanges",101 as Any),("duration",0 as Any),("state","unrecognized" as Any),("completedCount",2 as Any)] {
        var corrupt=saved;corrupt[field]=bad
        let invalid=try! JSONDecoder().decode(PairedDialogue.self,from:JSONSerialization.data(withJSONObject:corrupt))
        precondition(!invalid.valid,"invalid persisted dialogue: \(field)")
    }
    try! NativeWorkbench.safeDirectory(prefs)
    let original=prefs.appendingPathComponent("中文.txt");try! Data("TEST/FIXTURE only".utf8).write(to:original)
    precondition(try! WebTransferFile.read(original)==Data("TEST/FIXTURE only".utf8))
    let link=prefs.appendingPathComponent("link.txt");try! FileManager.default.createSymbolicLink(at:link,withDestinationURL:original)
    do {_ = try WebTransferFile.read(link);fatalError("symlink accepted")} catch {}
    print("PAIRED_POLICY_SCOPE_CONCESSION_SIDES_STALE_AND_FILE_IDENTITY_PASS");exit(0)
}
if mode == "paired_recovery" {
    try! NativeWorkbench.safeDirectory(prefs)
    try! NativeWorkbench.save(["kind0":"ChatGPT","kind1":"Claude","url0":base.absoluteString,"url1":base.absoluteString],at:prefs.appendingPathComponent("paired-workbench.json"))
    var r=WebHandoffReceipt(source:base.absoluteString,message:"TEST/FIXTURE",text:"non-sensitive",hash:"hash",provider:"Claude",targetPane:1,targetURL:base.absoluteString,binding:"fixture",dialogueID:"TEST-DIALOGUE")
    r.state="sending";r.mayHaveSent=true
    let d=PairedDialogue(id:"TEST-DIALOGUE",providers:["ChatGPT","Claude"],conversations:[base.absoluteString,base.absoluteString],roles:["a","b"],firstText:"TEST/FIXTURE",maxExchanges:6,duration:120,createdAt:Date().timeIntervalSince1970,state:"running",sentCount:1,pendingID:r.id)
    try! JSONEncoder().encode([r]).write(to:prefs.appendingPathComponent("web-handoff-receipts.json"))
    try! JSONEncoder().encode(d).write(to:prefs.appendingPathComponent("paired-dialogue.json"))
    let work=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("unexpected business action")})
    precondition(work.dialogue?.state=="paused" && work.dialogue?.pendingID==r.id)
    precondition(work.webTransfers.count==1 && work.webTransfers[0].mayHaveSent==true)
    precondition(work.activeWebQueues.isEmpty && work.webTransfers[0].state=="unknown")
    work.tickDialogue();precondition(work.webTransfers.count==1)
    work.stopDialogue();precondition(work.dialogue?.state=="stopped" && work.dialogue?.pendingID==r.id)
    work.startDialogue()
    precondition(work.dialogue?.id==d.id && work.webTransfers.count==1,"unknown old submission was replaced")
    print("PAIRED_RESTART_PAUSED_UNKNOWN_NOT_REPLAYED_STOP_PRESERVES_RECEIPT_PASS");exit(0)
}

if mode == "auxiliary_window_close" {
    app.setActivationPolicy(.regular)
    try! NativeWorkbench.save(["kind0":"ChatGPT","kind1":"Claude","url0":base.absoluteString,"url1":base.absoluteString],at:prefs.appendingPathComponent("paired-workbench.json"))
    let work=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("no business action")})
    work.start();work.showWebHistory()
    DispatchQueue.main.asyncAfter(deadline:.now()+0.4){
        precondition(work.handoffWindow?.isVisible==true)
        work.handoffWindow?.performClose(nil)
        DispatchQueue.main.asyncAfter(deadline:.now()+0.2){
            precondition(work.handoffWindow?.isVisible==false && work.window?.isKeyWindow==true,"history close must return to its own workbench")
            work.showDialogue();work.dialogueWindow?.performClose(nil)
            DispatchQueue.main.asyncAfter(deadline:.now()+0.2){
                precondition(work.dialogueWindow?.isVisible==false && work.window?.isKeyWindow==true,"dialogue close must return to its own workbench")
                precondition(work.webTransfers.isEmpty && work.dialogue==nil,"window close must not send or resume")
                print("AUXILIARY_CLOSE_RETURNS_OWN_WORKBENCH_WITHOUT_DISPATCH_PASS");exit(0)
            }
        }
    };app.run();exit(0)
}
if mode == "history_restore" {
    let left=base.appendingPathComponent("a"),right=base.appendingPathComponent("b")
    try! NativeWorkbench.save(["kind0":"ChatGPT","kind1":"Claude","url0":left.absoluteString,"url1":right.absoluteString],at:prefs.appendingPathComponent("paired-workbench.json"))
    let work=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("no business action")})
    work.start()
    let r=WebHandoffReceipt(source:left.appendingPathComponent("original").absoluteString,message:"TEST/FIXTURE",text:"non-sensitive",hash:"hash",provider:"Claude",targetPane:1,targetURL:right.appendingPathComponent("original").absoluteString,binding:"fixture")
    work.webTransfers=[r];work.showWebHistory()
    func ready(){
        work.webPanes[0]!.web.evaluateJavaScript("!!document.getElementById('draft')") { ok,_ in
            guard ok as? Bool==true else{DispatchQueue.main.asyncAfter(deadline:.now()+0.1,execute:ready);return}
            work.webPanes[1]!.web.evaluateJavaScript("!!document.getElementById('draft')") { ok,_ in
                guard ok as? Bool==true else{DispatchQueue.main.asyncAfter(deadline:.now()+0.1,execute:ready);return}
                var uncertain=WebHandoffReceipt(source:left.absoluteString,message:"TEST/FIXTURE",text:"non-sensitive",hash:"hash",provider:"Claude",targetPane:1,targetURL:base.absoluteString,binding:"fixture")
                uncertain.state="unknown";uncertain.mayHaveSent=true
                precondition(work.canInspectCurrentTarget(uncertain) && !work.currentTargetMatches(uncertain),"first-send reconciliation must be read-only")
                uncertain.state="sent";uncertain.resolvedURL=uncertain.targetURL
                precondition(work.canInspectCurrentTarget(uncertain),"landing-page acknowledgement must allow exact read-only reconciliation")
                uncertain.mayHaveSent=false;precondition(!work.canInspectCurrentTarget(uncertain))
                uncertain.mayHaveSent=true;uncertain.resolvedURL=right.appendingPathComponent("different").absoluteString
                precondition(!work.canInspectCurrentTarget(uncertain),"do not rebind a proven destination")
                precondition(!work.canInspectCurrentTarget(r),"existing conversation mismatch stays blocked")
                work.webPanes[0]!.web.evaluateJavaScript("document.getElementById('draft').value='TEST/FIXTURE draft'") {_,_ in
                    work.openHistoryConversations()
                    DispatchQueue.main.asyncAfter(deadline:.now()+0.3){
                        precondition(work.webPanes[0]!.web.url==left && work.webPanes[1]!.web.url==right)
                        precondition(work.handoffDetail.string.contains("No page was changed"))
                        work.webPanes[0]!.web.evaluateJavaScript("document.getElementById('draft').value='';const b=document.createElement('button');b.id='stop';b.setAttribute('aria-label','Stop');document.body.append(b)") {_,_ in
                            work.openHistoryConversations()
                            DispatchQueue.main.asyncAfter(deadline:.now()+0.3){
                                precondition(work.webPanes[0]!.web.url==left && work.webPanes[1]!.web.url==right)
                                work.webPanes[0]!.web.evaluateJavaScript("document.getElementById('stop').remove()") {_,_ in
                                    work.openHistoryConversations()
                                    DispatchQueue.main.asyncAfter(deadline:.now()+0.7){
                                        precondition(work.webPanes[0]!.web.url==URL(string:r.source) && work.webPanes[1]!.web.url==URL(string:r.targetURL))
                                        precondition(work.webTransfers.count==1 && work.webTransfers[0].id==r.id && work.dialogue==nil)
                                        print("HISTORY_RESTORE_EXACT_CONVERSATIONS_DRAFT_BUSY_GUARD_NO_DISPATCH_PASS");exit(0)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    };ready();DispatchQueue.main.asyncAfter(deadline:.now()+20){fatalError("history restore timeout")};app.run();exit(0)
}
if mode == "paired_attachment_scope_ui" {
    let work=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("no business action")})
    let old=WebTransferFile(id:"OLD",name:"OLD-authorized.txt",mime:"text/plain",size:3,hash:"old1234567890",source:"TEST")
    let next=WebTransferFile(id:"NEXT",name:"NEXT-selected.png",mime:"image/png",size:4,hash:"new1234567890",source:"TEST")
    work.webFileSelections=[0:[next]]
    work.dialogue=PairedDialogue(id:"OLD-DIALOGUE",providers:["ChatGPT","Claude"],conversations:["https://chatgpt.com/","https://claude.ai/new"],roles:["A","B"],firstText:"TEST/FIXTURE",maxExchanges:6,duration:900,createdAt:Date().timeIntervalSince1970,state:"finished",files:[old])
    work.showDialogue()
    for state in ["finished","stopped","paused","running"] {
        work.dialogue?.state=state;work.refreshDialogueUI()
        let label=work.dialogueStatus!.stringValue
        precondition(label.contains("NEXT-selected.png")==["finished","stopped","paused"].contains(state))
        precondition(label.contains("OLD-authorized.txt")==["paused","running"].contains(state))
        if state != "running" {precondition(label.contains("Files selected for a new exchange"))}
        precondition(work.dialogue?.files==[old] && work.webFileSelections[0]==[next],"rendering must not change authorization")
        precondition(work.webTransfers.isEmpty && work.dialogue?.sentCount==0,"review must never dispatch")
    }
    print("PAIRED_ATTACHMENT_SCOPE_UI_TERMINAL_NEW_AND_PAUSED_OLD_NO_DISPATCH_PASS");exit(0)
}
if ["paired_auto","paired_auto_navigation","paired_auto_late_navigation","paired_auto_late_changed"].contains(mode) {
    let left=mode.hasPrefix("paired_auto_late_") ? base : base.appendingPathComponent("a"),right=mode.hasPrefix("paired_auto_late_") ? base.appendingPathComponent("new") : base.appendingPathComponent("b")
    try! NativeWorkbench.save(["kind0":"ChatGPT","kind1":"Claude","url0":left.absoluteString,"url1":right.absoluteString],at:prefs.appendingPathComponent("paired-workbench.json"))
    let work=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("no business action")})
    work.start();work.showDialogue()
    work.dialogueWindow?.contentView?.layoutSubtreeIfNeeded()
    precondition(work.dialogueRounds!.frame.width>=60 && work.dialogueMinutes!.frame.width>=60,"budget input collapsed")
    work.webPanes[1]!.showNotice("Claude sign-in is available. Sign in on this page; no task has been sent.")
    work.webPanes[1]!.reconcileAccessNotice("idle")
    precondition(work.webPanes[1]!.notice.stringValue=="Claude input is ready. Handoff sends only the instruction you select.")
    work.webPanes[1]!.showNotice("Delivery unknown")
    work.webPanes[1]!.reconcileAccessNotice("idle")
    precondition(work.webPanes[1]!.notice.stringValue=="Delivery unknown","activity erased a delivery warning")
    work.webPanes[0]!.showNotice("ChatGPT could not finish loading. Retry with ↻, or open this page in Safari. Your saved work is retained.")
    work.webPanes[0]!.reconcileAccessNotice("idle")
    precondition(work.webPanes[0]!.notice.isHidden,"stale load warning remained over a usable composer")
    func begin(){
        work.webPanes[1]!.web.evaluateJavaScript("document.getElementById('draft') != null") { loaded,_ in
            guard loaded as? Bool==true,work.webPanes[0]!.web.url==left else{DispatchQueue.main.asyncAfter(deadline:.now()+0.15,execute:begin);return}
            work.dialogueText!.string="TEST/FIXTURE six exact exchanges 中文 <code>"
            work.dialogueRounds!.stringValue="3";work.dialogueMinutes!.stringValue="2"
            work.startDialogue()
            func finish(){
                if mode=="paired_auto_late_changed",work.dialogue?.state=="paused" {
                    precondition(work.webTransfers.count==1 && work.dialogue!.sentCount==1 && work.dialogue!.completedCount==0)
                    precondition(work.webTransfers[0].resolvedURL==right.absoluteString,"changed body must not rebind the destination")
                    print("LATE_NAVIGATION_CHANGED_RECEIPT_PAUSES_NO_REBIND_NO_SECOND_SEND_PASS");exit(0)
                }
                if work.dialogue?.state=="paused" {fatalError("auto paused: \(work.dialogue?.reason ?? "")")}
                guard work.dialogue?.state=="finished" else{DispatchQueue.main.asyncAfter(deadline:.now()+0.2,execute:finish);return}
                precondition(work.dialogue!.completedCount==6 && work.webTransfers.count==6)
                precondition(Set(work.webTransfers.map(\.id)).count==6)
                precondition(work.webTransfers.map(\.targetPane)==[1,0,1,0,1,0])
                precondition(work.webTransfers.allSatisfy{$0.state=="reply" && $0.resultHash != nil})
                if mode=="paired_auto_navigation" || mode=="paired_auto_late_navigation" {
                    precondition(work.dialogue!.conversations.allSatisfy{$0.hasSuffix("/conversation")},"new conversation was not bound by exact receipt")
                }
                let last=work.webTransfers.last!
                work.inspectWebTransfer(last.id,target:work.webPanes[0]!)
                work.inspectWebTransfer(last.id,target:work.webPanes[0]!)
                DispatchQueue.main.asyncAfter(deadline:.now()+0.5){
                    precondition(work.webTransfers.count==6)
                    work.webPanes[0]!.web.evaluateJavaScript("window.sends") { a,_ in
                        work.webPanes[1]!.web.evaluateJavaScript("window.sends") { b,_ in
                            precondition(a as? Int==3 && b as? Int==3)
                            precondition(work.webTransfers.last?.inspection=="reply")
                            print("SIMULATED_WEBKIT_THREE_ROUNDTRIPS_NO_DUPLICATE_INSPECTION_PASS");exit(0)
                        }
                    }
                }
            };finish()
        }
    };begin();DispatchQueue.main.asyncAfter(deadline:.now()+60){fatalError("paired auto timeout")};app.run();exit(0)
}

if mode == "one_click" {
    try! NativeWorkbench.save(["kind0":"ChatGPT","kind1":"DeepSeek","url0":base.absoluteString,"url1":base.absoluteString], at:prefs.appendingPathComponent("paired-workbench.json"))
    let work=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("no business action")})
    work.start();let target=work.webPanes[1]!,origin=work.webPanes[0]!
    func readyClick(){
        target.web.evaluateJavaScript("document.getElementById('draft') != null") { ready,_ in
            guard ready as? Bool == true, origin.web.url != nil else { DispatchQueue.main.asyncAfter(deadline:.now()+0.1,execute:readyClick);return }
            work.handoff("TEST/FIXTURE one click",source:base,from:0,message:"chosen-message")
            work.handoff("TEST/FIXTURE one click",source:base,from:0,message:"chosen-message")
            precondition(work.window!.sheets.isEmpty,"generic second confirmation returned")
            DispatchQueue.main.asyncAfter(deadline:.now()+7){
                target.web.evaluateJavaScript("window.sends") { count,_ in
                    precondition(count as? Int == 1 && work.webTransfers.count == 1)
                    let r=work.webTransfers[0];precondition(r.state == "reply" && r.message == "chosen-message" && r.text == "TEST/FIXTURE one click")
                    work.nyraStatus.snapshot { data in
                        let event=try! JSONSerialization.jsonObject(with:data) as! [String:Any]
                        // The fixture has no verified live composer-state adapter. A durable
                    // reply alone no longer fabricates a live whole-workspace status.
                    precondition(event["state"] as? String == "disconnected" && event["activity_side"] as? String == "both")
                        print("ONE_CLICK_EXACTLY_ONCE_REAL_RESPONSE_AND_METADATA_PASS");exit(0)
                    }
                }
            }
        }
    }
    readyClick();DispatchQueue.main.asyncAfter(deadline:.now()+20){fatalError("one click timeout")};app.run();exit(0)
}
if mode == "ledger" {
    let r=WebHandoffReceipt(source:"https://chatgpt.com/c/test",message:"m1",text:"only selected instruction",hash:"sha",provider:"DeepSeek",targetPane:1,targetURL:"https://chat.deepseek.com/a/chat/test",binding:"epoch|1|DeepSeek|test")
    let data=try JSONEncoder().encode([r]); let decoded=try JSONDecoder().decode([WebHandoffReceipt].self,from:data)[0]
    precondition(decoded.provider=="DeepSeek" && decoded.text==r.text && decoded.id==r.id)
    precondition(decoded.request(inspectOnly:true)["inspectOnly"] as? Bool == true)
    precondition(decoded.card["provider"] as? String == "DeepSeek")
    var attached=decoded
    attached.files=[WebTransferFile(id:"TEST-FILE",name:"TEST.txt",mime:"text/plain",size:5,hash:"TEST-HASH",source:"/not-readable/TEST.txt")]
    let inspection=attached.request(inspectOnly:true)
    let manifest=inspection["files"] as! [[String:Any]]
    precondition(manifest.count==1 && manifest[0]["hash"] as? String == "TEST-HASH")
    precondition(manifest[0]["source"] == nil && manifest[0]["base64"] == nil,"inspect must never reread or transfer bytes/paths")
    precondition(attached.request(inspectOnly:false)["files"] == nil,"only the explicit dispatch may resolve upload bytes")
    let claude=WebHandoffReceipt(source:"https://chatgpt.com/c/test",message:"c1",text:"selected Claude instruction",hash:"sha-c",provider:"Claude",targetPane:1,targetURL:"https://claude.ai/new",binding:"epoch|1|Claude|test")
    precondition(claude.request(inspectOnly:false)["draftOnly"] as? Bool == false)
    precondition(claude.request(inspectOnly:true)["inspectOnly"] as? Bool == true)
    precondition(claude.card["provider"] as? String == "Claude")
    print("LEDGER_PASS");exit(0)
}
if mode == "nyra_lifecycle" {
    var callbacks=0
    let bridge=NativeNyra(stateRoot:prefs) { _ in callbacks += 1 }
    // macOS may no longer supply bundle metadata at termination. This event
    // must still re-observe our own helper rather than preserve a stale label.
    NSWorkspace.shared.notificationCenter.post(name:NSWorkspace.didTerminateApplicationNotification,object:nil)
    RunLoop.current.run(until:Date().addingTimeInterval(0.15))
    precondition(callbacks == 1,"termination without application metadata was ignored")
    withExtendedLifetime(bridge) {}
    print("NYRA_LIFECYCLE_PASS");exit(0)
}
if mode == "states" {
    try! NativeWorkbench.save(["kind0":"ChatGPT","kind1":"DeepSeek","url0":base.absoluteString,"url1":base.absoluteString], at:prefs.appendingPathComponent("paired-workbench.json"))
    let work=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("no business action")})
    var r=WebHandoffReceipt(source:base.absoluteString,message:"m",text:"TEST/FIXTURE",hash:"sha",provider:"DeepSeek",targetPane:1,targetURL:base.absoluteString,binding:"test")
    r.state="sending";r.mayHaveSent=true;work.webTransfers=[r]
    work.applyWebResponse(r.id,response:["state":"unknown"],dispatchResponse:true)
    work.applyWebResponse(r.id,response:["state":"target_changed"])
    precondition(work.webTransfers[0].state=="unknown" && work.webTransfers[0].mayHaveSent==true)
    precondition(work.webTransfers[0].card["retryable"] as? Bool == false)
    work.applyWebResponse(r.id,response:["state":"sent","conversationURL":base.appendingPathComponent("new-chat").absoluteString])
    work.applyWebResponse(r.id,response:["state":"verification"])
    precondition(work.webTransfers[0].state=="sent")
    work.applyWebResponse(r.id,response:["state":"reply","reply":"TEST/FIXTURE reply"])
    work.applyWebResponse(r.id,response:["state":"unknown"])
    precondition(work.webTransfers[0].state=="reply" && work.webTransfers[0].result=="TEST/FIXTURE reply")
    var q=r;q.id="QUEUE-FIXTURE";q.state="sending";q.createdAt+=1;work.webTransfers.append(q)
    work.applyWebResponse(q.id,response:["state":"busy"],dispatchResponse:true)
    precondition(work.webTransfers[1].state=="queued" && work.webTransfers[1].mayHaveSent==false)
    work.rightPicker.selectItem(at:1);work.changePane(work.rightPicker)
    precondition(work.webTransfers[1].state=="queue_paused" && !work.activeWebQueues.contains(q.id))
    precondition(work.webTransfers[0].provider=="DeepSeek")
    work.showWebHistory();work.handoffPicker.selectItem(at:0);work.cancelHistoryDelivery()
    precondition(work.webTransfers[1].state=="cancelled" && work.webTransfers[0].state=="reply")
    work.handoffPicker.selectItem(at:1);work.cancelHistoryDelivery()
    precondition(work.webTransfers[0].state=="reply")
    let restarted=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{})
    precondition(restarted.activeWebQueues.isEmpty && restarted.webTransfers[0].state=="reply")
    print("STICKY_SEND_BOUND_QUEUE_CANCEL_RECOVERY_PASS");exit(0)
}
if mode == "queue_dispatch" {
    try! NativeWorkbench.save(["kind0":"ChatGPT","kind1":"DeepSeek","url0":base.absoluteString,"url1":base.absoluteString], at:prefs.appendingPathComponent("paired-workbench.json"))
    let work=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("no business action")})
    work.start(); let target=work.webPanes[1]!
    var queued=false
    func readyQueue() {
        target.web.evaluateJavaScript("document.getElementById('draft') != null") { ready,_ in
            guard ready as? Bool == true else { DispatchQueue.main.asyncAfter(deadline:.now()+0.1,execute:readyQueue); return }
            guard !queued else{return};queued=true
            for n in 1...2 {
                var r=WebHandoffReceipt(source:base.absoluteString,message:"m\(n)",text:"TEST/FIXTURE queued \(n)",hash:"fixture-\(n)",provider:"DeepSeek",targetPane:1,targetURL:base.absoluteString,binding:"fixture")
                r.id="QUEUE-\(n)";r.createdAt=Double(n);r.state="queued";r.mayHaveSent=false;work.webTransfers.append(r)
                work.observeQueuedTransfer(r.id,target:target)
            }
            DispatchQueue.main.asyncAfter(deadline:.now()+10) {
                target.web.evaluateJavaScript("JSON.stringify({sends:window.sends,messages:[...document.querySelectorAll('[data-role=user]')].map(e=>e.textContent)})") { result,_ in
                    let value=try! JSONSerialization.jsonObject(with:Data((result as! String).utf8)) as! [String:Any]
                    precondition(value["sends"] as? Int == 2)
                    precondition(value["messages"] as? [String] == ["[TWOS handoff QUEUE-1]\nTEST/FIXTURE queued 1","[TWOS handoff QUEUE-2]\nTEST/FIXTURE queued 2"])
                    precondition(work.webTransfers.allSatisfy{$0.state=="reply" && $0.mayHaveSent==true})
                    work.showWebHistory();work.handoffPicker.selectItem(at:0);work.historySelectionChanged()
                    precondition(!work.historyButtons[1].0.isEnabled && !work.historyButtons[2].0.isEnabled)
                    print("QUEUE_FIFO_EXACTLY_ONCE_PASS");exit(0)
                }
            }
        }
    }
    readyQueue();DispatchQueue.main.asyncAfter(deadline:.now()+20){fatalError("queue timeout")};app.run();exit(0)
}
let b=NativeWorkbench(preferences:prefs,translate:{$0},openProjects:{fatalError("no project action")},serviceHome:base,handoffResources:resources)
b.start()
var started=false
func probe(){
    b.web.evaluateJavaScript("document.getElementById('draft') != null") { ready,error in
        guard ready as? Bool == true else { DispatchQueue.main.asyncAfter(deadline:.now()+0.05,execute:probe);return }
        guard !started else{return};started=true
        let id="TEST-FIXTURE-"+mode
        var request:[String:Any] = ["id":id,"text":"TEST/FIXTURE 非敏感 <script>文字</script>\nline two", "targetURL":base.absoluteString,"provider":["chatgpt_semantic","chatgpt_bubble","chatgpt_bubble_changed","chatgpt_markup","chatgpt_markup_changed","upload_chatgpt_bubble","upload_chatgpt_renamed","upload_menu_control"].contains(mode) ? "ChatGPT":(mode.hasPrefix("claude") ? "Claude":"DeepSeek"),"inspectOnly":mode=="inspect_missing","preflightOnly":mode=="preflight","readinessOnly":mode=="readiness","draftOnly":mode=="draft","resumeDraft":["resume_missing","resume_exact"].contains(mode)]
        if mode.contains("markup") { request["text"]=(request["text"] as! String)+"\nInline `const label = \"待办 ✓\";` and ``value `tick` end``" }
        if mode.hasPrefix("upload_") {
            let names=mode=="upload_same_name" ? ["同名.txt","同名.txt"] : ["资料.txt","图片.png","文档.pdf"]
            request["files"]=names.enumerated().map { index,name -> [String:Any] in
                // SIMULATED transport bytes: this test checks identity and delivery,
                // not production document parsing or a real model reading a PDF.
                let data=Data("TEST/FIXTURE original bytes \(index) 中文".utf8)
                return ["id":"file-\(index)","name":name,"mime":name.hasSuffix(".png") ? "image/png" : name.hasSuffix(".pdf") ? "application/pdf":"text/plain","size":data.count,"hash":mode=="upload_corrupt" ? "wrong":NativeCodex.digest(data),"base64":data.base64EncodedString()]
            }
        }
        let setup:String
        switch mode {
        case "upload_history": setup="document.body.insertAdjacentHTML('beforeend','<div data-role=user><div data-testid=attachment>OLD-HISTORY</div><span role=progressbar>old output</span></div>')"
        case "upload_foreign": setup="document.getElementById('draft-area').insertAdjacentHTML('beforeend','<div data-testid=attachment>PRIVATE-EXISTING</div>')"
        case "upload_foreign_image": setup="document.getElementById('draft-area').insertAdjacentHTML('beforeend','<div role=button aria-label=OTHER.png>image</div>')"
        case "upload_async_input", "upload_changed_input": setup="const field=document.getElementById('draft');const original=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value');let pending=false;Object.defineProperty(field,'value',{get(){return pending?'TEST/FIXTURE editor not settled':original.get.call(this)},set(v){original.set.call(this,v)}});field.addEventListener('input',()=>{pending=true;"+(mode=="upload_async_input" ? "setTimeout(()=>pending=false,200)":"")+"})"
        case "upload_delayed_control": setup="const f=document.querySelector('input[type=file]');f.remove();setTimeout(()=>document.getElementById('draft-area').append(f),400)"
        case "upload_menu_control": setup="const f=document.querySelector('input[type=file]');f.remove();const b=document.createElement('button');b.setAttribute('aria-label','Add files and more');b.onclick=()=>{b.setAttribute('aria-expanded','true');document.getElementById('draft-area').append(f)};document.getElementById('draft-area').append(b)"
        case "upload_scoped_control": setup="document.body.insertAdjacentHTML('beforeend','<aside><input type=file multiple></aside>')"
        case "upload_ambiguous_control": setup="document.getElementById('draft-area').insertAdjacentHTML('beforeend','<input type=file multiple>')"
        case "upload_no_control": setup="document.querySelector('input[type=file]').remove()"
        case "upload_switch": setup="document.documentElement.dataset.changeDuringUpload='yes'"
        case "challenge": setup="document.body.insertAdjacentHTML('afterbegin','<h1>正在进行安全验证</h1>')"
        case "resume_exact": setup="document.getElementById('draft').value='PREPARE_EXACT_DRAFT'"
        case "existing": setup="document.getElementById('draft').value='KEEP EXISTING'"
        case "busy": setup="document.body.insertAdjacentHTML('afterbegin','<button aria-label=Stop>stop</button>')"
        case "origin": setup="void(0)"
        case "cancel": setup="document.getElementById('draft').addEventListener('input',()=>{window.twosTransferLease='changed';})"
        default: setup="void(0)"
        }
        let actualSetup = mode == "resume_exact" ? "document.getElementById('draft').value=prompt" : setup
        b.web.callAsyncJavaScript(actualSetup,arguments:["prompt":"[TWOS handoff "+id+"]\n"+(request["text"] as! String)],in:nil,in:NativeWorkbench.handoffWorld) { _ in
            var req=request
            if mode=="origin" {req["targetURL"]="https://evil.test/"}
            b.webTransfer(req) { response in
                let expected=["challenge":"verification","existing":"draft_conflict","busy":"busy","origin":"target_changed","draft":"draft","cancel":"target_changed","preflight":"ready","readiness":"input_ready","inspect_missing":"unknown","chatgpt_bubble_changed":"unknown","claude_markup_changed":"unknown","chatgpt_markup_changed":"unknown","resume_missing":"unknown","deepseek_streaming":"sent","claude_streaming":"sent","upload_corrupt":"unsupported","upload_foreign":"draft_conflict","upload_foreign_image":"draft_conflict","upload_changed_input":"draft","upload_no_control":"unsupported","upload_ambiguous_control":"unsupported","upload_switch":"unknown"][mode] ?? "reply"
                if mode=="claude_markup" {precondition((response["reply"] as? String)?.contains("TEST/FIXTURE response") == true && (response["reply"] as? String)?.contains("PROGRESS") == false && (response["reply"] as? String)?.contains("待办 ✓") == true,"final body must exclude public progress but preserve code") }
                if mode=="claude_chrome" {precondition(response["reply"] as? String=="TEST/FIXTURE response","UI chrome is not answer text")}
                precondition(response["state"] as? String == expected,"\(mode): \(response)")
                b.web.evaluateJavaScript("JSON.stringify({sends:window.sends,draft:document.getElementById('draft').value,inlineCode:document.querySelectorAll('[data-testid=user-message] code').length})") { value,_ in
                    let facts=try! JSONSerialization.jsonObject(with:Data((value as! String).utf8)) as! [String:Any]
                    if mode.contains("markup") {precondition(facts["inlineCode"] as? Int==2,"fixture must actually render both inline code fragments")}
                    let sends = ["upload_exact","upload_async_input","upload_delayed_control","upload_menu_control","upload_scoped_control","upload_same_name","upload_history","upload_claude_labels","upload_chatgpt_cards","upload_chatgpt_renamed","send","spa","deepseek_shape","deepseek_streaming","chatgpt_semantic","chatgpt_bubble","chatgpt_bubble_changed","chatgpt_markup","chatgpt_markup_changed","upload_chatgpt_bubble","claude","claude_streaming","claude_chrome","claude_markup","claude_markup_changed","resume_exact"].contains(mode)
                    precondition(facts["sends"] as? Int == (sends ? 1:0),"side effect")
                    if mode=="existing" {precondition(facts["draft"] as? String == "KEEP EXISTING")}
                    func verifySingleDispatch() {
                        if sends {
                            var inspect=request;inspect["inspectOnly"]=true
                            func reconcile() {
                                b.webTransfer(inspect) { duplicate in
                                    precondition(duplicate["state"] as? String == (["chatgpt_bubble_changed","claude_markup_changed","chatgpt_markup_changed"].contains(mode) ? "unknown":"reply"))
                                    b.web.evaluateJavaScript("window.sends") { value,_ in precondition(value as? Int==1);print("CROSS_SEND_ONCE_PASS");exit(0) }
                                }
                            }
                            if ["deepseek_streaming","claude_streaming"].contains(mode) { b.web.evaluateJavaScript("window.finishStream()") { _,_ in reconcile() } }
                            else if mode=="claude_chrome" { b.web.evaluateJavaScript("document.querySelector('[role=toolbar]').textContent='3 minutes ago'") { _,_ in reconcile() } }
                            else { reconcile() }
                        }else{print("CROSS_\(mode)_PASS");exit(0)}
                    }
                    if ["upload_async_input","upload_delayed_control","upload_menu_control","upload_scoped_control"].contains(mode) || mode=="upload_exact" || mode=="upload_same_name" || mode=="upload_history" || mode=="upload_claude_labels" || mode=="upload_chatgpt_cards" || mode=="upload_chatgpt_renamed" {
                        precondition((response["attachments"] as? [[String:Any]])?.count == (request["files"] as? [[String:Any]])?.count)
                        b.web.evaluateJavaScript("JSON.stringify(window.uploaded)") { raw,_ in
                            let bytes=try! JSONSerialization.jsonObject(with:Data((raw as! String).utf8)) as! [[String:Any]]
                            let selected=request["files"] as! [[String:Any]]
                            precondition(bytes.count==selected.count)
                            for i in bytes.indices {precondition(bytes[i]["base64"] as? String==selected[i]["base64"] as? String && bytes[i]["name"] as? String==selected[i]["name"] as? String)}
                            // Do not exit the process until the asynchronous
                            // byte identity check has actually completed.
                            verifySingleDispatch()
                        }
                    } else { verifySingleDispatch() }
                }
            }
        }
    }
}
probe();DispatchQueue.main.asyncAfter(deadline:.now()+20){fatalError("fixture timeout")};app.run()
'''
    source=root/'main.swift';source.write_text(code);binary=root/'cross'
    run=subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(root/'cache'),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120)
    assert run.returncode==0,run.stderr
    return binary

@pytest.mark.parametrize('mode',['paired_attachment_scope_ui','auxiliary_window_close','history_restore','paired_policy','paired_auto','paired_auto_navigation','paired_auto_late_navigation','paired_auto_late_changed','paired_recovery','upload_exact','upload_async_input','upload_changed_input','upload_delayed_control','upload_menu_control','upload_scoped_control','upload_ambiguous_control','upload_same_name','upload_history','upload_claude_labels','upload_chatgpt_cards','upload_chatgpt_renamed','upload_foreign_image','upload_corrupt','upload_foreign','upload_no_control','upload_switch','nyra_selected_target','nyra_selection_async','owner_result_binding','one_click','nyra_socket_queue','nyra_file_wait','nyra_status','ledger','nyra_lifecycle','states','queue_dispatch','send','spa','deepseek_shape','deepseek_streaming','chatgpt_semantic','chatgpt_bubble','chatgpt_bubble_changed','chatgpt_markup','chatgpt_markup_changed','upload_chatgpt_bubble','claude','claude_streaming','claude_chrome','claude_markup','claude_markup_changed','preflight','readiness','inspect_missing','resume_missing','resume_exact','challenge','existing','busy','origin','draft','cancel'])
def test_exact_target_single_dispatch_and_preflight(cross_harness,tmp_path,mode):
    class Fixture(BaseHTTPRequestHandler):
        def do_GET(self):
            body='''<!doctype html><meta charset="utf-8"><h1>TEST/FIXTURE · synthetic provider</h1><div id="draft-area"><div data-testid="composer"><textarea id="draft"></textarea></div><button aria-label="Send" id="send">Send</button></div><script>
window.sends=0;document.getElementById('draft').addEventListener('input',()=>{if(window.cancelDuringInput)window.twosTransferLease='changed';});
document.getElementById('send').onclick=()=>{window.sends++;let user=document.createElement('div');user.dataset.role='user';user.textContent=document.getElementById('draft').value;document.getElementById('draft').value='';document.body.append(user);let reply=document.createElement('div');reply.dataset.role='assistant';reply.textContent='TEST/FIXTURE response';document.body.append(reply);
if(TEST_MODE==='upload_menu_control'){user.dataset.messageAuthorRole='user';reply.dataset.messageAuthorRole='assistant';}
if(TEST_MODE==='spa')history.pushState({},'', '/new-conversation');
if(TEST_MODE==='deepseek_shape'||TEST_MODE==='deepseek_streaming'){delete user.dataset.role;delete reply.dataset.role;user.className='ds-collapsible-text';reply.className='ds-markdown ds-assistant-message-main-content';for(const el of [user,reply]){const wrap=document.createElement('div');wrap.className='ds-message';el.before(wrap);wrap.append(el);}}
window.finishStream=()=>{const idle=document.createElement('div');idle.setAttribute('role','button');idle.className='ds-button--primary ds-button--circle ds-button--disabled';idle.innerHTML='<svg width=16 height=16><path d="M8.3125 0.980206C8.66767 1.05312 8.97902 1.2042 9.2627 1.43235C9.48724 1.613 9.73029 1.85795 9.97949 2.10716L14.707 6.8347L13.293 8.24876L9 3.95579V15.0417H7V3.95579L2.70703 8.24876L1.29297 6.8347L6.02051 2.10716C6.26971 1.85795 6.51277 1.613 6.7373 1.43235C6.97662 1.23988 7.28445 1.04404 7.6875 0.980206C7.8973 0.947029 8.1031 0.955183 8.3125 0.980206Z"></path></svg>';document.getElementById('draft').after(idle);};if(TEST_MODE==='deepseek_shape')window.finishStream();
if(TEST_MODE.startsWith('claude')){delete user.dataset.role;delete reply.dataset.role;user.dataset.testid='user-message';reply.className='font-claude-response';reply.dataset.isStreaming=TEST_MODE==='claude_streaming'?'true':'false';window.finishStream=()=>{reply.dataset.isStreaming='false';};}
if(TEST_MODE.includes('markup')){
 document.documentElement.dataset.twosFixtureProvider=TEST_MODE.startsWith('claude')?'Claude':'ChatGPT';user.dataset.testid='user-message';
 const source=user.textContent;user.textContent='';let end=0;
 for(const m of source.matchAll(/(`+)([^\\n]*?)\\1/g)){user.append(document.createTextNode(source.slice(end,m.index)));const code=document.createElement('code');code.textContent=m[2];user.append(code);end=m.index+m[0].length;}user.append(document.createTextNode(source.slice(end)));
 if(TEST_MODE.endsWith('markup_changed'))user.querySelector('code').textContent='const label = "CHANGED";';
 reply.className='assistant-message';reply.innerHTML='<div class="group/status"><span>PROGRESS</span><span role=status>PROGRESS</span></div><div class="standard-markdown"><p>TEST/FIXTURE response</p><pre><code>const label = "待办 ✓";</code></pre></div>';
}
if(TEST_MODE==='claude_chrome'){reply.insertAdjacentHTML('beforeend','<div role=toolbar>Now<button>Copy</button></div>');}
if(TEST_MODE==='upload_chatgpt_renamed'){user.insertAdjacentHTML('afterbegin','<button>File.txt</button><span>File.txt document </span><button>Image.png</button>');}
if(TEST_MODE==='chatgpt_semantic'||TEST_MODE==='upload_chatgpt_renamed'){delete user.dataset.role;delete reply.dataset.role;reply.dataset.messageAuthorRole='assistant';const h=document.createElement('h4');h.textContent='你说：';user.before(h);const a=document.createElement('h4');a.textContent='ChatGPT 说：';reply.before(a);}
if(['chatgpt_bubble','chatgpt_bubble_changed','chatgpt_markup','chatgpt_markup_changed','upload_chatgpt_bubble'].includes(TEST_MODE)){delete user.dataset.role;delete reply.dataset.role;reply.dataset.messageAuthorRole='assistant';user.setAttribute('data-user-message-bubble','true');const body=document.createElement('div');body.setAttribute('data-search-result-target','');body.append(...user.childNodes);if(TEST_MODE==='chatgpt_bubble_changed')body.append('UNEXPECTED EXTRA CONTENT');user.replaceChildren(body);user.append(document.createTextNode('…'));const h=document.createElement('h4');h.textContent='你说：你说：';user.before(h);if(TEST_MODE==='upload_chatgpt_bubble')user.insertAdjacentHTML('afterbegin','<button>File.txt</button><span>File.txt document</span>');}
if(TEST_MODE==='chatgpt_semantic'||TEST_MODE==='upload_chatgpt_renamed'){const h=user.previousElementSibling;const wrap=document.createElement('section');h.before(wrap);wrap.append(h,user);const activity=document.createElement('section');activity.innerHTML='<button>Thought for 1m 35s</button><span>Analysis output 1</span>';wrap.after(activity);}
};
</script>'''.replace('window.sends=0;',f'const TEST_MODE={mode!r};window.sends=0;').encode()
            if mode.startswith('upload_'):
                body=body.replace(b'<textarea id="draft">',b'<input type=file multiple><textarea id="draft">')
                body=body.replace(b'</script>',b"""
window.uploaded=[];document.querySelector('input[type=file]').onchange=async e=>{
 if(document.documentElement.dataset.changeDuringUpload==='yes'){history.pushState({},'', '/other');return;}
 for(const f of e.target.files){const a=new Uint8Array(await f.arrayBuffer());window.uploaded.push({name:f.name,base64:btoa(String.fromCharCode(...a))});const chip=document.createElement(TEST_MODE==='upload_claude_labels'?'button':'div');if(TEST_MODE==='upload_claude_labels'){chip.setAttribute('aria-label',String.fromCodePoint(31227,38500)+' '+f.name);}else{chip.dataset.testid='attachment';chip.textContent=f.name;}if(TEST_MODE==='upload_chatgpt_cards'||TEST_MODE==='upload_chatgpt_renamed'){
 delete chip.dataset.testid;chip.setAttribute('role','button');const shown=TEST_MODE==='upload_chatgpt_renamed'?f.name.slice(0,f.name.lastIndexOf('.'))+'(1)'+f.name.slice(f.name.lastIndexOf('.')):f.name;chip.setAttribute('aria-label',shown);chip.textContent='';
 const wrapper=document.createElement('div');wrapper.append(chip);const remove=document.createElement('button');remove.setAttribute('aria-label','Remove '+shown);wrapper.append(remove);document.getElementById('draft-area').append(wrapper);
 }else{document.getElementById('draft-area').append(chip);} }
};
</script>""")
            if mode in ('history_restore','paired_auto','paired_auto_navigation','paired_auto_late_navigation','paired_auto_late_changed'):
                provider='ChatGPT' if self.path in ('/a','/') else 'Claude'
                body=('''<!doctype html><html data-twos-fixture-provider="PROVIDER"><meta charset=utf-8><h1>TEST/FIXTURE automatic participant PROVIDER</h1><textarea id=draft></textarea><button aria-label=Send id=send>Send</button><script>
window.sends=0;document.getElementById('send').onclick=()=>{window.sends++;const user=document.createElement('div');user.dataset.messageAuthorRole='user';user.dataset.testid='user-message';user.textContent=document.getElementById('draft').value;document.body.append(user);document.getElementById('draft').value='';const reply=document.createElement('div');reply.dataset.messageAuthorRole='assistant';reply.dataset.isStreaming='false';reply.className='font-claude-response';reply.textContent='TEST/FIXTURE PROVIDER complete answer '+window.sends+' 中文\\nline two';document.body.append(reply);};
</script></html>''').replace('PROVIDER',provider).encode()
                if mode=='paired_auto_navigation':
                    body=body.replace(b'const user=document.createElement',b"if(window.sends===1)history.pushState({},'',location.pathname+'/conversation');setTimeout(()=>{const user=document.createElement")
                    body=body.replace(b'document.body.append(reply);};',b'document.body.append(reply);},window.sends===1?3200:0);};')
                if mode in ('paired_auto_late_navigation','paired_auto_late_changed'):
                    body=body.replace(b"const reply=document.createElement",br"if(window.sends===1)setTimeout(()=>history.pushState({},'',location.pathname.replace(/\/$/,'')+'/conversation'),350);setTimeout(()=>{const reply=document.createElement")
                    body=body.replace(b'document.body.append(reply);};',b'document.body.append(reply);},window.sends===1?3200:0);};')
                if mode=='paired_auto_late_changed':
                    body=body.replace(br"history.pushState({},'',location.pathname.replace(/\/$/,'')+'/conversation')",br"(history.pushState({},'',location.pathname.replace(/\/$/,'')+'/conversation'),user.textContent+=' CHANGED')")
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture);thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        executable=cross_harness
        if mode=='nyra_selected_target':
            # NSRunningApplication needs an actual bundle identity for the
            # unchanged snapshot PID/bundle checks; a naked test binary has none.
            import plistlib,shutil
            bundle=tmp_path/'Selected Nyra Fixture.app'
            executable=bundle/'Contents/MacOS/cross'
            executable.parent.mkdir(parents=True)
            shutil.copy2(cross_harness,executable)
            (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'com.tianma.tests.nyra.selected','CFBundleExecutable':'cross','CFBundlePackageType':'APPL'}))
        result=subprocess.run([str(executable),mode,str(tmp_path/'profile'),f'http://127.0.0.1:{server.server_port}/',str(ROOT/'static_cockpit')],capture_output=True,text=True,timeout=75 if mode in ('paired_auto','paired_auto_navigation','paired_auto_late_navigation','paired_auto_late_changed') else 30)
        assert result.returncode==0,result.stdout+result.stderr
        assert 'PASS' in result.stdout
    finally:server.shutdown();server.server_close();thread.join()


def test_nyra_termination_publishes_invisible_and_stops_resources(tmp_path):
    """SIMULATED native lifecycle; actual production termination handler, no model."""
    import os
    source_root=ROOT/'packaging/macos/nyra/Sources'
    source=tmp_path/'main.swift'
    code=(source_root/'main.swift').read_text().split('if CommandLine.arguments.contains("--self-test")',1)[0]
    code+=r'''
let app=NSApplication.shared
app.setActivationPolicy(.prohibited)
let companion=Companion()
try! FileManager.default.createDirectory(at:companion.stateDirectory,withIntermediateDirectories:true)
companion.wardrobe=Wardrobe(schemaVersion:1,character:"TEST/FIXTURE",mode:"test",defaultOutfit:"runtime-default",outfits:[Outfit(id:"runtime-default",name:"fixture",file:"fixture.png",note:"TEST/FIXTURE",width:1,height:1,runtimeReady:false)])
companion.library=try! JSONDecoder().decode(R4Library.self,from:Data(contentsOf:URL(fileURLWithPath:CommandLine.arguments[1]))).validated()
companion.panel=PetPanel(contentRect:NSRect(x:-10000,y:-10000,width:16,height:16),styleMask:.borderless,backing:.buffered,defer:false)
companion.panelView=PanelView(frame:NSRect(x:0,y:0,width:16,height:16))
companion.stageView=StageView(frame:NSRect(x:0,y:0,width:900,height:800))
companion.live.markConnected(true)
companion.reactive.setWork(.idle,simulation:false,connected:true,celebrate:false,now:0)
companion.reconcileAnimation()
precondition(companion.stageView!.truth.stringValue.contains("TWOS"))
companion.live.markConnected(false)
companion.reactive.setWork(.disconnected,simulation:false,connected:false,celebrate:false,now:1)
companion.reconcileAnimation()
precondition(companion.stageView!.truth.stringValue.contains("TWOS NOT_CONNECTED"),"stale stage connection label")

companion.stage=NSWindow(contentRect:NSRect(x:-10000,y:-10000,width:16,height:16),styleMask:.borderless,backing:.buffered,defer:false)
companion.panel.orderFrontRegardless();companion.stage!.orderFrontRegardless()
companion.publishVisibility()
func state() -> [String:Any] { try! JSONSerialization.jsonObject(with:Data(contentsOf:companion.stateDirectory.appendingPathComponent("visibility-state.json"))) as! [String:Any] }
precondition(state()["visible"] as? Bool == true)
companion.applicationWillTerminate(Notification(name:NSApplication.willTerminateNotification))
precondition(!companion.panel.isVisible && !companion.stage!.isVisible)
precondition(state()["visible"] as? Bool == false && state()["pending"] as? Bool == false)
precondition(companion.frameTimer == nil && companion.hoverTimer == nil)
let preference=try! JSONSerialization.jsonObject(with:Data(contentsOf:companion.preferenceDirectory.appendingPathComponent("visibility-preference.json"))) as! [String:Bool]
precondition(preference["visible"] == true,"normal exit must preserve desired visible preference")
let saved=try! JSONSerialization.jsonObject(with:Data(contentsOf:companion.stateDirectory.appendingPathComponent("preview-settings.json"))) as! [String:Any]
precondition(saved["outfit"] as? String == "runtime-default")
print("NYRA_TERMINATION_PASS")
'''
    source.write_text(code)
    binary=tmp_path/'nyra-lifecycle'
    inputs=[str(p) for p in sorted(source_root.glob('*.swift')) if p.name!='main.swift']
    build=subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(tmp_path/'cache'),'-framework','AppKit','-framework','AVFoundation',*inputs,str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120)
    assert build.returncode==0,build.stderr
    run=subprocess.run([str(binary),str(source_root.parent/'Resources/runtime/r4.json'),'--diagnostic-root',str(tmp_path/'profile')],env={**os.environ,'NYRA_ISOLATED_ENGINEERING':'1'},capture_output=True,text=True,timeout=15)
    assert run.returncode==0,run.stdout+run.stderr
    assert 'NYRA_TERMINATION_PASS' in run.stdout


def test_nyra_local_socket_authenticates_exact_helper_and_never_returns_body(cross_harness,tmp_path):
    """REAL_LOCAL_IPC, synthetic state; no Nyra consumer/product acceptance claim."""
    import json, plistlib, shutil, time
    for name in ['Allowed.app','Wrong.app']:
        app=tmp_path/name
        (app/'Contents/MacOS').mkdir(parents=True)
        shutil.copy2(cross_harness,app/'Contents/MacOS/TestNyra')
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'TestNyra','CFBundleIdentifier':'com.tianma.workos.nyra','CFBundlePackageType':'APPL'}))
        subprocess.run(['codesign','--force','--sign','-',str(app)],check=True,capture_output=True)
    args=[str(tmp_path),'http://127.0.0.1/',str(ROOT/'static_cockpit')]
    server=subprocess.Popen([str(cross_harness),'status_server',*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        deadline=time.monotonic()+15
        while not (tmp_path/'ready').exists() and time.monotonic()<deadline and server.poll() is None: time.sleep(.05)
        assert (tmp_path/'ready').exists()
        wrong=subprocess.run([str(tmp_path/'Wrong.app/Contents/MacOS/TestNyra'),'status_client',*args],capture_output=True,text=True,timeout=8)
        assert wrong.returncode==0 and wrong.stdout.strip()=='DENIED',wrong.stderr+wrong.stdout
        command=[str(tmp_path/'Allowed.app/Contents/MacOS/TestNyra'),'status_client',*args]
        allowed=subprocess.run(command,capture_output=True,text=True,timeout=8)
        assert allowed.returncode==0,allowed.stderr
        event=json.loads(allowed.stdout)
        assert event['state']=='completed_unverified' and event['session_id']=='TEST-SESSION'
        assert event['task_id']=='TEST-TASK' and event['schema_version']=='twos.nyra.status.v1'
        assert set(event)=={'schema_version','producer_instance_id','event_id','sequence','timestamp','session_id','task_id','state','source','simulation'}
        repeat=subprocess.run(command,capture_output=True,text=True,timeout=8)
        assert json.loads(repeat.stdout)==event, 'snapshot/reconnect must not increment or replay'
        # Real macOS IPC disconnect race, not a simulated send result. The
        # normal reader must still succeed after the authenticated peer closes.
        import os, signal
        os.kill(server.pid, signal.SIGSTOP)
        abandoned=subprocess.Popen([str(tmp_path/'Allowed.app/Contents/MacOS/TestNyra'),'status_client_abandon',*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            time.sleep(.35)
            os.kill(server.pid, signal.SIGCONT)
            closed_out,closed_err=abandoned.communicate(timeout=8)
            assert abandoned.returncode==0 and 'CLIENT_CLOSED' in closed_out,closed_err
            assert server.poll() is None, 'abandoned authenticated client killed producer'
            recovered=subprocess.run(command,capture_output=True,text=True,timeout=8)
            assert recovered.returncode==0 and json.loads(recovered.stdout)==event
        finally:
            if server.poll() is None: os.kill(server.pid, signal.SIGCONT)
            if abandoned.poll() is None: abandoned.terminate();abandoned.communicate(timeout=5)
    finally:
        server.terminate();server.communicate(timeout=10)


def test_real_r4_consumer_mutually_authenticates_producer_and_deduplicates(cross_harness,tmp_path):
    """REAL_LOCAL_IPC with TEST identifiers; no production event/model/GUI claim."""
    import plistlib, shutil, time
    apps={}
    for name,identifier in [('Producer','com.tianma.workos'),('OtherProducer','com.tianma.workos'),('Allowed','com.tianma.workos.nyra')]:
        app=tmp_path/(name+'.app');exe=app/'Contents/MacOS/Probe';exe.parent.mkdir(parents=True)
        shutil.copy2(cross_harness,exe)
        (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'Probe','CFBundleIdentifier':identifier,'CFBundlePackageType':'APPL'}))
        subprocess.run(['codesign','--force','--sign','-',str(app)],check=True,capture_output=True)
        apps[name]=(app,exe)
    args=[str(tmp_path),'http://127.0.0.1/',str(ROOT/'static_cockpit')]
    server=subprocess.Popen([str(apps['Producer'][1]),'status_server',*args],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        deadline=time.monotonic()+8
        while not (tmp_path/'ready').exists() and time.monotonic()<deadline: time.sleep(.05)
        assert (tmp_path/'ready').exists()
        for name,expected in [('OtherProducer','STRICT_R4_DENIED'),('Producer','STRICT_R4_READONLY_PEER_AND_DEDUP_PASS')]:
            result=subprocess.run([str(apps['Allowed'][1]),'status_client_strict',str(tmp_path),'http://127.0.0.1/',str(apps[name][0])],capture_output=True,text=True,timeout=8)
            assert result.returncode==0 and expected in result.stdout,result.stdout+result.stderr
    finally:
        server.terminate();server.communicate(timeout=10)
