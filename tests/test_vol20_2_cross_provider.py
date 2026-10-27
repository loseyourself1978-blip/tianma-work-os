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
    for name in ('CodexAttachments.swift','CodexTelemetry.swift','NativeCodex.swift','IntegratedWorkbench.swift'):
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
    print("NYRA_STATUS_PRIVACY_DEDUP_RECONNECT_TERMINAL_PASS");exit(0)
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
                        precondition(event["state"] as? String == "completed_unverified" && event["task_id"] as? String == r.id)
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
        let request:[String:Any] = ["id":id,"text":"TEST/FIXTURE 非敏感 <script>文字</script>\nline two", "targetURL":base.absoluteString,"provider":mode=="chatgpt_semantic" ? "ChatGPT":(mode.hasPrefix("claude") ? "Claude":"DeepSeek"),"inspectOnly":mode=="inspect_missing","preflightOnly":mode=="preflight","readinessOnly":mode=="readiness","draftOnly":mode=="draft","resumeDraft":["resume_missing","resume_exact"].contains(mode)]
        let setup:String
        switch mode {
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
                let expected=["challenge":"verification","existing":"draft_conflict","busy":"busy","origin":"target_changed","draft":"draft","cancel":"target_changed","preflight":"ready","readiness":"input_ready","inspect_missing":"unknown","resume_missing":"unknown","deepseek_streaming":"sent","claude_streaming":"sent"][mode] ?? "reply"
                precondition(response["state"] as? String == expected,"\(mode): \(response)")
                b.web.evaluateJavaScript("JSON.stringify({sends:window.sends,draft:document.getElementById('draft').value})") { value,_ in
                    let facts=try! JSONSerialization.jsonObject(with:Data((value as! String).utf8)) as! [String:Any]
                    let sends = ["send","spa","deepseek_shape","deepseek_streaming","chatgpt_semantic","claude","claude_streaming","resume_exact"].contains(mode)
                    precondition(facts["sends"] as? Int == (sends ? 1:0),"side effect")
                    if mode=="existing" {precondition(facts["draft"] as? String == "KEEP EXISTING")}
                    if sends {
                        var inspect=request;inspect["inspectOnly"]=true
                        func reconcile() {
                            b.webTransfer(inspect) { duplicate in
                                precondition(duplicate["state"] as? String == "reply")
                                b.web.evaluateJavaScript("window.sends") { value,_ in precondition(value as? Int==1);print("CROSS_SEND_ONCE_PASS");exit(0) }
                            }
                        }
                        if ["deepseek_streaming","claude_streaming"].contains(mode) { b.web.evaluateJavaScript("window.finishStream()") { _,_ in reconcile() } }
                        else { reconcile() }
                    }else{print("CROSS_\(mode)_PASS");exit(0)}
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

@pytest.mark.parametrize('mode',['nyra_selected_target','nyra_selection_async','owner_result_binding','one_click','nyra_socket_queue','nyra_file_wait','nyra_status','ledger','nyra_lifecycle','states','queue_dispatch','send','spa','deepseek_shape','deepseek_streaming','chatgpt_semantic','claude','claude_streaming','preflight','readiness','inspect_missing','resume_missing','resume_exact','challenge','existing','busy','origin','draft','cancel'])
def test_exact_target_single_dispatch_and_preflight(cross_harness,tmp_path,mode):
    class Fixture(BaseHTTPRequestHandler):
        def do_GET(self):
            body='''<!doctype html><meta charset="utf-8"><h1>TEST/FIXTURE · synthetic provider</h1><textarea id="draft"></textarea><button aria-label="Send" id="send">Send</button><script>
window.sends=0;document.getElementById('draft').addEventListener('input',()=>{if(window.cancelDuringInput)window.twosTransferLease='changed';});
document.getElementById('send').onclick=()=>{window.sends++;let user=document.createElement('div');user.dataset.role='user';user.textContent=document.getElementById('draft').value;document.getElementById('draft').value='';document.body.append(user);let reply=document.createElement('div');reply.dataset.role='assistant';reply.textContent='TEST/FIXTURE response';document.body.append(reply);
if(TEST_MODE==='spa')history.pushState({},'', '/new-conversation');
if(TEST_MODE==='deepseek_shape'||TEST_MODE==='deepseek_streaming'){delete user.dataset.role;delete reply.dataset.role;user.className='ds-collapsible-text';reply.className='ds-markdown ds-assistant-message-main-content';for(const el of [user,reply]){const wrap=document.createElement('div');wrap.className='ds-message';el.before(wrap);wrap.append(el);}}
window.finishStream=()=>{const idle=document.createElement('div');idle.setAttribute('role','button');idle.className='ds-button--primary ds-button--circle ds-button--disabled';idle.innerHTML='<svg width=16 height=16><path d="M8.3125 0.980206C8.66767 1.05312 8.97902 1.2042 9.2627 1.43235C9.48724 1.613 9.73029 1.85795 9.97949 2.10716L14.707 6.8347L13.293 8.24876L9 3.95579V15.0417H7V3.95579L2.70703 8.24876L1.29297 6.8347L6.02051 2.10716C6.26971 1.85795 6.51277 1.613 6.7373 1.43235C6.97662 1.23988 7.28445 1.04404 7.6875 0.980206C7.8973 0.947029 8.1031 0.955183 8.3125 0.980206Z"></path></svg>';document.getElementById('draft').after(idle);};if(TEST_MODE==='deepseek_shape')window.finishStream();
if(TEST_MODE.startsWith('claude')){delete user.dataset.role;delete reply.dataset.role;user.dataset.testid='user-message';reply.className='font-claude-response';reply.dataset.isStreaming=TEST_MODE==='claude_streaming'?'true':'false';window.finishStream=()=>{reply.dataset.isStreaming='false';};}
if(TEST_MODE==='chatgpt_semantic'){delete user.dataset.role;delete reply.dataset.role;reply.dataset.messageAuthorRole='assistant';const h=document.createElement('h4');h.textContent='你说：';user.before(h);const a=document.createElement('h4');a.textContent='ChatGPT 说：';reply.before(a);}
};
</script>'''.replace('window.sends=0;',f'const TEST_MODE={mode!r};window.sends=0;').encode()
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
        result=subprocess.run([str(executable),mode,str(tmp_path/'profile'),f'http://127.0.0.1:{server.server_port}/',str(ROOT/'static_cockpit')],capture_output=True,text=True,timeout=30)
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
