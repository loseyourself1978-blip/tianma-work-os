let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let profile = URL(fileURLWithPath: CommandLine.arguments[1])
let resources = URL(fileURLWithPath: CommandLine.arguments[2])
let roomID = UUID().uuidString
let library = profile.appendingPathComponent("team-r2"), dir = library.appendingPathComponent(roomID)
do {
  try NativeWorkbench.safeDirectory(profile.appendingPathComponent("unused/../traversal"))
  fatalError("Accepted traversal")
} catch let error as CocoaError where error.code == .fileWriteNoPermission {}
try NativeWorkbench.safeDirectory(dir)
let scenario = CommandLine.arguments[3]
let member = TeamMember(role: "Planner", product: "ChatGPT", provider: "OpenAI", model: scenario == "multiround" ? "Medium" : (["mismatch","unreportedPin"].contains(scenario) ? "GPT-6.0" : ""), displayName: "Ada", duties: ["Planner"])
let folder = try NativeCodex.inspectDirectory(dir.path, isolated: true)
var restored = TeamRun(id: roomID, created: 1, goal: "Offline recovery fixture", csv: "", folder: folder, members: [member])
var conversation = TeamConversation()
for messageIndex in 0..<2 {
  var draft = TeamDraft()
  draft.text = scenario == "leaveUnknown" && messageIndex == 1 ? "Summarize the later fixture." : "Give the status of this synthetic fixture."
  try conversation.submit(draft, members: [member], language: "en")
}
restored.conversation = conversation; restored.state = "paused"; restored.reason = "reviewerUnavailable"; restored.next = "Planner"
if ["uncertain","pendingHistory","leaveUnknown"].contains(scenario) {
  restored.state = "running"
  let prompt = try restored.prompt(), a = try restored.begin(prompt)
  var receipt = WebHandoffReceipt(source: "team:" + roomID, message: a.id, text: prompt, hash: a.inputHash,
     provider: "ChatGPT", targetPane: 0, targetURL: TeamMember.homes["ChatGPT"]! + (["pendingHistory","leaveUnknown"].contains(scenario) ? "c/bound" : ""), binding: roomID)
  receipt.mayHaveSent = true
  restored.attempts[0].web = receipt; restored.attempts[0].state = "unknown"
  restored.state = "paused"; restored.reason = "unconfirmed"
}
if scenario == "manifest" {
  let outputURL = profile.appendingPathComponent("output")
  try NativeWorkbench.safeDirectory(outputURL)
  let output = try NativeCodex.inspectDirectory(outputURL.path, isolated: true)
  let untouched = outputURL.appendingPathComponent("personal.txt")
  try Data("private".utf8).write(to: untouched)
  let workspace = TeamWorkspace(root: resources, preferences: dir, translate: { $0 }, managed: true)
  let reviewer = TeamMember(role: "Reviewer", product: "Claude", provider: "Anthropic", model: "")
  let builder = TeamMember(role: "Builder", product: "Codex", provider: "OpenAI", model: "")
  restored.members += [builder, reviewer]
  conversation.output = output
  conversation.plans = [TeamChatPlan(round: conversation.round, requirements: ["Return a checked site"], builder: "Builder", reviewer: "Reviewer")]
  let original = ["index.html": "<title>Example</title>", "app.js": "void 0", "REVIEW.md": "First edition"]
  func revision(_ files: [String: String]) throws -> TeamFileRevision {
    TeamFileRevision(id: UUID().uuidString, round: conversation.round, producer: "Builder",
                     attempt: UUID().uuidString, time: 1, files: files, digest: NativeCodex.digest(try TeamFiles.bytes(files)))
  }
  let first = try revision(original), amendment = try revision(["REVIEW.md": "Evidence"])
  conversation.revisions = [first]
  conversation.queue = []
  restored.conversation = conversation
  try workspace.setupRoom(restored)
  try workspace.publishRoomFiles()
  try workspace.changeRoom { $0.conversation?.revisions.append(amendment) }
  try workspace.publishRoomFiles()
  let published = workspace.run!.conversation!.revisions.last!
  let measured = published.deliveryManifest!.files
  precondition(Set(measured.keys) == Set(original.keys) && measured["index.html"]?.contentRevision == first.digest)
  precondition(measured["REVIEW.md"]?.contentRevision == amendment.digest)
  try workspace.checkVisibleRevision(published)
  let review = TeamAssignment(message: conversation.inputs[0].id, member: "Reviewer", kind: "review",
                              instruction: "Verify the files", round: conversation.round, frozen: amendment.digest)
  var attempt = TeamAttempt(id: UUID().uuidString, role: "Reviewer", version: 2, inputHash: "test", started: 2)
  attempt.assignment = review
  attempt.state = "completed"
  try workspace.changeRoom { run in
    run.attempts = [attempt]
    run.conversation?.revisions[1].deliveryManifest = nil
    run.conversation?.revisions[1].reviewAttempt = attempt.id
    run.conversation?.revisions[1].verdict = "needs_evidence"
    run.state = "paused"
    run.reason = "decision"
  }
  var stopped = workspace.run!
  stopped.conversation?.stoppedByUser = true
  precondition(stopped.reviewNeedingFileEvidence == nil)
  try workspace.recheckDeliveredFiles(attempt.id)
  let recovered = workspace.run!
  let next = recovered.conversation!.queue
  precondition(next.count == 1 && next[0].member == "Reviewer" && next[0].frozen == amendment.digest)
  precondition(recovered.reviewNeedingFileEvidence == nil && recovered.attempts.last?.id == attempt.id)
  let prompt = try recovered.prompt()
  precondition(prompt.contains("verifiedDeliveryFiles") && prompt.contains(measured["app.js"]!.sha256))
  precondition(!prompt.contains(untouched.lastPathComponent) && !prompt.contains(output.path))
  do {
    try workspace.recheckDeliveredFiles(attempt.id)
    fatalError("Duplicate dispatch")
  } catch TeamError.wrongVersion {}
  let tampered = outputURL.appendingPathComponent("app.js")
  try Data("user edit".utf8).write(to: tampered)
  do {
    try workspace.checkVisibleRevision(recovered.conversation!.revisions.last!)
    fatalError("Changed inherited file was approved")
  } catch TeamError.fileConflict {}
  print("PASS partial update keeps verified owned outputs, legacy same-revision review, unrelated file excluded, edited output blocks approval")
  exit(0)
}
if scenario == "timeoutBoundary" {
  var stoppedRoute = restored
  stoppedRoute.state = "running"
  var routeAttempt = try stoppedRoute.begin(stoppedRoute.prompt())
  var unsent = WebHandoffReceipt(source:"team:"+roomID,message:routeAttempt.id,text:routeAttempt.promptText!,
      hash:routeAttempt.inputHash,provider:"ChatGPT",targetPane:0,targetURL:"https://chatgpt.com/",binding:roomID)
  unsent.state="target_changed";unsent.mayHaveSent=false;routeAttempt.web=unsent
  stoppedRoute.attempts=[routeAttempt];stoppedRoute.state="paused";stoppedRoute.reason="reviewerUnavailable"
  var uncertainRoute=stoppedRoute;uncertainRoute.attempts[0].web?.mayHaveSent=true
  precondition(!uncertainRoute.recoverUnsentRouteChange() && uncertainRoute.pending != nil)
  precondition(stoppedRoute.recoverUnsentRouteChange() && stoppedRoute.pending == nil &&
    stoppedRoute.retryableUnsentAssignment?.id == routeAttempt.assignment?.id)

  let builder = TeamMember(role:"Builder", product:"Codex", provider:"OpenAI", model:"fixture")
  var run=restored, c=conversation
  let step=TeamAssignment(message:c.inputs[0].id,member:"Builder",kind:"build",instruction:"Create the fixture",round:c.round)
  c.plans=[TeamChatPlan(round:c.round,requirements:["fixture"],builder:"Builder",reviewer:"Reviewer")]
  c.queue=[step]; run.members.append(builder); run.members.append(TeamMember(role:"Reviewer",product:"Claude",provider:"Anthropic",model:"")); run.conversation=c; run.selectNextChatStep()
  var attempt=try run.begin(run.prompt())
  precondition(attempt.observationExpired(at:attempt.started+600))
  attempt.thread="thread-fixture";attempt.clientID="client-fixture";attempt.transportState="running"
  precondition(!attempt.observationExpired(at:attempt.started+600))
  precondition(attempt.observationExpired(at:attempt.started+1800))
  precondition(!attempt.observationExpired(at:attempt.started+1800,lastBuildActivity:attempt.started+1798))
  precondition(attempt.observationExpired(at:attempt.started+2400,lastBuildActivity:attempt.started+1800))
  precondition(attempt.observationExpired(at:attempt.started+5400,lastBuildActivity:attempt.started+5399))
  run.attempts=[attempt];run.stopRequested=true;run.state="stopping";run.reason="timeout";run.recordState()
  run.attempts[0].state="interrupted";run.attempts[0].transportState="interrupted"
  run.state="stopped";run.reason="interrupted";run.recordState()
  var completed=run
  let produced = #"{"text":"Ready","files":{"index.html":"<title>Fixture</title>",".gitignore":"dist/"}}"#
  completed.attempts[0].state="completed";completed.attempts[0].transportState="completed"
  completed.attempts[0].turn="provider-turn";completed.reason="timeout"
  completed.attempts[0].resultHash=NativeCodex.digest(Data(produced.utf8))
  do {
    try completed.recoverCompletedBuild(attempt.id,text:produced+"!",thread:"thread-fixture",turn:"provider-turn")
    fatalError("Accepted a changed result")
  } catch TeamError.wrongVersion {}
  try completed.recoverCompletedBuild(attempt.id,text:produced,thread:"thread-fixture",turn:"provider-turn")
  precondition(completed.attempts.count==1 && completed.next=="Reviewer")
  precondition(completed.conversation?.revisions.last?.files["gitignore.example"]=="dist/")
  precondition(completed.conversation?.revisions.last?.files[".gitignore"]==nil)
  precondition(completed.conversation?.revisions.last?.originalPaths?["gitignore.example"]==".gitignore")
  precondition(completed.conversation?.queue.map(\.kind)==["review"] && completed.timedOutBuild==nil)
  var unknown=run;unknown.attempts[0].transportState="unknown";precondition(unknown.retryableTimedOutBuild==nil)
  var manual=run;manual.reason="stopped";precondition(manual.retryableTimedOutBuild==nil)
  try run.retryTimedOutBuild(attempt.id)
  precondition(run.conversation?.queue == [step] && run.next=="Builder" && run.attempts.count==1)
  precondition(run.retryableTimedOutBuild==nil)
  print("PASS bounded production deadline, user stop and unknown delivery protected, same plan retries once")
  exit(0)
}
try TeamFiles.bytes(restored).write(to: dir.appendingPathComponent(roomID + ".json"))
try Data(roomID.utf8).write(to: dir.appendingPathComponent("current"))
try Data(roomID.utf8).write(to: library.appendingPathComponent("selected"))
let team = TeamChatWorkspace(root: resources, preferences: profile, translate: { $0 })
let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1024, height: 700),
                      styleMask: [.titled, .closable], backing: .buffered, defer: false)
window.contentView = team.web; window.makeKeyAndOrderFront(nil); team.present()
func webView(_ view: NSView?) -> WKWebView? {
  if let found = view as? WKWebView { return found }
  return view?.subviews.compactMap { webView($0) }.first
}
struct ProbeFailure: Error, CustomStringConvertible { let description: String }
@MainActor func waitUntil(_ page: WKWebView, _ predicate: String, timeout: TimeInterval = 20) async throws {
  let limit = Date().addingTimeInterval(timeout)
  while Date() < limit {
    if (try? await page.evaluateJavaScript(predicate)) as? Bool == true { return }
    try await Task.sleep(nanoseconds: 100_000_000)
  }
  let details = try? await team.web.evaluateJavaScript("JSON.stringify([room?.state,room?.reason,room?.recovery,room?.attempts.map(a=>a.state),document.querySelector('#notice').innerText])")
  throw ProbeFailure(description: predicate + " | " + String(describing: details))
}
@MainActor func press(_ title: String) async throws {
  let selector = "[...document.querySelectorAll('#notice button')].find(b=>b.innerText==='" + title + "')"
  try await waitUntil(team.web, "Boolean("+selector+")")
  _ = try await team.web.evaluateJavaScript(selector + ".click();true")
}
Task { @MainActor in
  do {
    if ["uncertain","pendingHistory","leaveUnknown"].contains(scenario) {
      try await waitUntil(team.web, "room?.pending && room.recovery.uncertain")
      try await press("Open member window")
      guard let provider = NSApp.windows.first(where: { $0.title.contains("Ada") && $0.title.contains("ChatGPT") }).flatMap({webView($0.contentView)}) else { throw ProbeFailure(description:"Missing original member window") }
      try await waitUntil(provider, "Boolean(document.querySelector('[data-testid=login-button]'))")
      _ = try await provider.evaluateJavaScript("document.querySelector('[data-testid=login-button]').click();true")
      if scenario == "pendingHistory" {
        _ = try await provider.evaluateJavaScript("history.pushState(null,'','/c/viewed-history');document.querySelector('textarea').value='unrelated draft';true")
        try await press("Check original conversation")
        try await waitUntil(team.web, "room.recovery.state==='preserveMemberWindow'")
        try await waitUntil(provider, "location.pathname==='/c/viewed-history' && document.querySelector('textarea').value==='unrelated draft'")
        _ = try await provider.evaluateJavaScript("document.querySelector('textarea').value='';true")
      }
      try await press("Check original conversation")
      try await waitUntil(team.web, "room.recovery.state==='retainedEmpty' && document.querySelector('#notice').innerText.includes('composer is empty')")
      if scenario == "pendingHistory" { try await waitUntil(provider, "location.pathname==='/c/bound' && deliveries===0") }
      if scenario == "leaveUnknown" {
        try await press("Keep original unconfirmed · check next instruction")
        try await waitUntil(team.web, "room.recovery.state==='webReady' && room.attempts.length===1")
        let journal=try TeamWorkspace.readRecord(roomID, from:dir)
        guard journal.pending == nil, journal.attempts[0].state == "leftUnconfirmed",
          journal.attempts[0].web?.mayHaveSent == true, journal.conversation?.queue.count == 1,
          journal.conversation?.queue.first?.instruction == "Summarize the later fixture.",
          (try await provider.evaluateJavaScript("deliveries")) as? Int == 0 else {
          throw ProbeFailure(description:"Later message replayed or old receipt lost")
        }
        print("PASS unresolved receipt durably retained; later instruction needs separate continuation, zero sends")
        team.shutdown();exit(0)
      }
      guard let w=restored.attempts.first?.web else { throw ProbeFailure(description:"Missing receipt") }
      let entered="[TWOS handoff " + w.id + "]\n" + w.text
      let _: Any = try await withCheckedThrowingContinuation { waiter in
        provider.callAsyncJavaScript("document.querySelector('textarea').value=text;return true", arguments:["text":entered],in:nil,in:.page) { waiter.resume(with:$0) }
      }
      try await press("Check original conversation")
      try await waitUntil(team.web, "room.recovery.state==='retainedExact' && !room.recovery.retained && !document.querySelector('#notice').innerText.includes('Send verified draft')")
      let saved=try TeamWorkspace.readRecord(roomID,from:dir)
      guard saved.attempts.count==1, saved.attempts[0].web?.mayHaveSent==true,
            (try await provider.evaluateJavaScript("deliveries")) as? Int == 0 else { throw ProbeFailure(description:"Inspection changed delivery") }
      print("PASS uncertain legacy receipt reports empty and exact inputs without sending, restoring or clearing uncertainty");team.shutdown();exit(0)
    }
    try await press("Refresh connection")
    try await waitUntil(team.web, "room.recovery.state==='webLogin' && room.attempts.length===0")
    if scenario == "stop" {
      _ = try await team.web.evaluateJavaScript("document.querySelector('#notice .primary').click();document.querySelector('#stop').click();true")
      try await waitUntil(team.web, "room.stop && room.state==='stopped' && !room.recovery.step && room.attempts.length===0 && room.queue.length===0")
      print("PASS stop cancels a recovery check");team.shutdown();exit(0)
    }
    _ = try await team.web.evaluateJavaScript("const typed=document.getElementById('message');typed.value=room.inputs[0].text;typed.dispatchEvent(new Event('input'));document.getElementById('send').click();true")
    try await waitUntil(team.web, "state.error==='alreadyQueued' && room.inputs.length===2 && room.attempts.length===0")
    try await press("Sign in to ChatGPT")
    guard let provider = NSApp.windows.first(where: { $0.title.contains("Ada") && $0.title.contains("ChatGPT") }).flatMap({ webView($0.contentView) }) else { throw ProbeFailure(description: "No member window") }
    _ = try await provider.evaluateJavaScript("document.querySelector('[data-testid=login-button]').click();true")
    let pickerTests = """
      const h=document.querySelector('header'),p=document.createElement('button');
      p.setAttribute('aria-label','选择 ChatGPT 模型');p.textContent='Pro';h.append(p);
      const model=window.twosProviderDOM.teamModel(true);
      const twin=p.cloneNode(true);h.append(twin);
      const ambiguous=window.twosProviderDOM.teamConnection().state;twin.remove();p.remove();
      const field=document.querySelector('textarea');field.value='An unrelated saved draft';
      const draft=window.twosProviderDOM.teamConnection(true).state;field.value='';
      const challenge=document.createElement('div');challenge.id='challenge-stage';h.append(challenge);
      const verification=window.twosProviderDOM.teamConnection(true).state;challenge.remove();
      return [model,ambiguous,draft,verification];
      """
    let statuses: Any = try await withCheckedThrowingContinuation { waiter in
      provider.callAsyncJavaScript(pickerTests,arguments:[:],in:nil,in:NativeWorkbench.handoffWorld) { waiter.resume(with:$0) }
    }
    guard statuses as? [String] == ["Pro","webSelection","webDraft","webVerification"] else {
      throw ProbeFailure(description: "Wrong rendered web evidence " + String(describing:statuses))
    }
    if ["multiround","mismatch"].contains(scenario) {
      _ = try await provider.evaluateJavaScript("const picker=document.createElement('button');picker.dataset.testid='model-selector';picker.textContent='\(scenario == "multiround" ? "Medium" : "GPT-6.2")';document.querySelector('header').append(picker);true")
    }
    guard let back = provider.window?.titlebarAccessoryViewControllers.compactMap({ $0.view as? NSButton })
      .first(where: { $0.title == "Back to chat · Check connection" }) else { throw ProbeFailure(description: "Missing return action") }
    if scenario == "firstHistory" {
      _ = try await provider.evaluateJavaScript("history.pushState(null,'','/c/browsed-for-login');true")
    }
    back.performClick(nil)
    if scenario == "unreportedPin" {
      try await waitUntil(team.web, "room.recovery.state==='webDefaultOnly' && room.attempts.length===0")
      try await press("Use website default for future turns")
      try await waitUntil(provider, "deliveries===0")
    }
    if scenario == "mismatch" {
      try await waitUntil(team.web, "room.recovery.state==='webMismatch' && room.recovery.expected==='GPT-6.0' && room.recovery.observed==='GPT-6.2'")
      try await press("Use GPT-6.2 for future turns")
      try await waitUntil(provider, "deliveries===0")
    }
    try await waitUntil(team.web, "room.recovery.state==='webReady' && room.inputs.length===2 && room.attempts.length===0")
    if ["retained", "manual", "missing"].contains(scenario) {
      _ = try await provider.evaluateJavaScript("const submit=document.querySelector('[data-testid=send-button]'); submit.disabled=true; true")
    }
    if ["richText","prepareError"].contains(scenario) {
      let configure = """
        const editor=document.createElement('div');
        editor.id='prompt-textarea'; editor.contentEditable='true'; editor.setAttribute('role','textbox');
        const send=document.querySelector('[data-testid=send-button]');
        editor.setAttribute('spellcheck','true'); input.replaceWith(editor); send.disabled=true;
        send.removeAttribute('data-testid'); send.setAttribute('aria-label','发送提示词'); send.textContent='';
        editor.addEventListener('input',e=>{send.disabled=e.inputType!=='insertText'||!e.isTrusted;});
        const voice=document.createElement('button'); voice.id='composer-submit-button';
        voice.type='button'; voice.dataset.testid='composer-speech-button'; send.after(voice);
        const other=document.createElement('form'); other.innerHTML='<button type="button">Send</button>'; document.body.append(other);
        const deliver=send.onclick;
        send.onclick=()=>{input.value=editor.innerText;editor.textContent='';deliver();};
        true
        """
      _ = try await provider.evaluateJavaScript(configure)
    }
    if scenario == "slowDraft" {
      // Delay only the first draft-stabilization callback beyond the native
      // deadline. Releasing it afterwards must not click or add a second turn.
      let _: Any = try await withCheckedThrowingContinuation { continuation in
        provider.callAsyncJavaScript("""
          const original=window.setTimeout.bind(window);
          window.setTimeout=(callback,delay,...args)=>{
            if(delay===50 && !window.fixtureDraftDelayed){
              window.fixtureDraftDelayed=true;
              return original(callback,9000,...args);
            }
            return original(callback,delay,...args);
          };return true
          """,arguments:[:],in:nil,in:NativeWorkbench.handoffWorld) { continuation.resume(with:$0) }
      }
    }
    if scenario == "prepareError" {
      let _: Any = try await withCheckedThrowingContinuation { continuation in
        provider.callAsyncJavaScript("document.execCommand=()=>{throw new Error('offline edit failure')};return true",
          arguments:[:],in:nil,in:NativeWorkbench.handoffWorld) { continuation.resume(with:$0) }
      }
    }
    if ["foldedEcho","foldedMismatch"].contains(scenario) {
      let configure = """
        const submit=document.querySelector('[data-testid=send-button]'),send=submit.onclick;
        window.expansions=0;window.wrongClicks=0;
        submit.onclick=()=>{
          send();const bubble=document.querySelector('[data-message-author-role=user]'),full=bubble.textContent;
          const wrap=document.createElement('section'), heading=document.createElement('h3');heading.textContent='你说：';
          const more=document.createElement('button');more.textContent='显示更多';
          const share=document.createElement('button');share.textContent='共享提示';share.onclick=()=>wrongClicks++;
          bubble.replaceWith(wrap);wrap.append(heading,bubble,more,share);if(\(scenario == "foldedEcho" ? "true" : "false"))heading.remove();bubble.textContent=full.slice(0,320);
          more.onclick=()=>{expansions++;bubble.textContent=full+\(scenario == "foldedMismatch" ? "'changed'" : "''");more.remove()};
          const foreign=wrap.cloneNode(true);foreign.querySelector('article').textContent='Different request';
          foreign.querySelector('button').onclick=()=>wrongClicks++;wrap.before(foreign);
        };true
        """
      _ = try await provider.evaluateJavaScript(configure)
    }
    if scenario == "delayedEcho" {
      _ = try await provider.evaluateJavaScript("""
        const submit=document.querySelector('[data-testid=send-button]'), send=submit.onclick;
        window.clicks=0;
        submit.onclick=()=>{window.clicks++;setTimeout(send,8500)};true
        """)
    }
    if scenario == "delayedRoute" {
      let setup = """
        const submit=document.querySelector('[data-testid=send-button]');
        const original=submit.onclick, route=history.pushState.bind(history);
        submit.onclick=()=>{
          history.pushState=()=>{};
          try{ original(); } finally{ history.pushState=route; }
          const sent=document.querySelector('[data-message-author-role=user]');
          const reply=document.querySelector('[data-message-author-role=assistant]');
          setTimeout(()=>{sent.remove();reply.remove()},3000);
          setTimeout(()=>document.querySelector('main').prepend(sent,reply),17500);
          setTimeout(()=>route(null,'','/c/first-send-fixture'),22000);
        }; true
        """
      _ = try await provider.evaluateJavaScript(setup)
    }
    try await press("Continue once · skip duplicate copies")
    if scenario == "foldedMismatch" {
      try await waitUntil(provider, "expansions===1 && deliveries===1 && wrongClicks===0")
      try await waitUntil(team.web, "room.state==='paused' && room.answers.length===0")
      let unchanged=try TeamWorkspace.readRecord(roomID,from:dir)
      guard unchanged.attempts.count==1,unchanged.pending?.resultHash==nil else {
        throw ProbeFailure(description:"Accepted a partially matching expanded request")
      }
      print("PASS expanded the bound user turn; full text mismatch kept unresolved, no duplicate")
      team.shutdown();exit(0)
    }
    if scenario == "delayedEcho" {
      try await waitUntil(team.web, "room.state==='running' && room.attempts[0]?.state==='unknown'")
    }
    if scenario == "delayedRoute" {
      try await waitUntil(team.web, "room.state==='running' && room.attempts[0]?.state==='sent'")
      try await waitUntil(provider, "deliveries===1 && !document.querySelector('[data-message-author-role=user]')")
      try await waitUntil(provider, "location.pathname==='/' && !!document.querySelector('[data-message-author-role=assistant]')")
      let awaiting = try TeamWorkspace.readRecord(roomID, from:dir)
      guard awaiting.state=="running", awaiting.pending?.state=="sent",
        awaiting.pending?.web?.resolvedURL==nil, awaiting.conversation?.answers.isEmpty==true else {
        throw ProbeFailure(description:"An unbound reply advanced the room or lost its sent receipt")
      }
    }
    if scenario == "slowDraft" {
      try await waitUntil(team.web, "room.recovery.retained && room.attempts.length===1")
      let saved = try TeamWorkspace.readRecord(roomID,from:dir)
      guard let a=saved.pending,let w=a.web,w.mayHaveSent==false,
            w.dispatchReason=="DRAFT_CHECK_TIMED_OUT_NO_MESSAGE_SENT" else {throw ProbeFailure(description:"Wrong preparation-timeout receipt")}
      var legacy=saved
      legacy.attempts[legacy.attempts.count-1].web?.dispatchReason="PREPARING_DRAFT_NO_MESSAGE_SENT"
      legacy.stopRequested=true;legacy.state="paused";legacy.reason="stopUnconfirmed"
      var stopped=legacy;stopped.conversation?.stoppedByUser=true
      var uncertain=legacy;uncertain.attempts[uncertain.attempts.count-1].web?.mayHaveSent=true
      precondition(!stopped.recoverTimedOutDraft() && !uncertain.recoverTimedOutDraft())
      precondition(legacy.recoverTimedOutDraft() && legacy.pending?.id==a.id && legacy.stopRequested==false)
      try await Task.sleep(nanoseconds:6500000000)
      try await waitUntil(provider,"deliveries===0")
      try await press("Check original conversation")
      try await waitUntil(team.web,"room.recovery.state==='retainedExact'")
      try await press("Send verified draft")
    }
    if scenario == "prepareError" {
      try await waitUntil(team.web, "room.recovery.retained && room.attempts.length===1")
      try await waitUntil(provider, "deliveries===0")
      let record = try TeamWorkspace.readRecord(roomID,from:dir)
      guard let w = record.pending?.web, w.state=="draft", w.mayHaveSent==false,
            w.dispatchReason?.hasPrefix("DRAFT_WEBKIT_")==true else {throw ProbeFailure(description:"Lost draft-only failure boundary")}
      print("PASS WebKit failed in the draft-only phase; no click; original operation recoverable")
      team.shutdown();exit(0)
    }
    if ["retained", "manual", "missing"].contains(scenario) {
      try await waitUntil(team.web, "room.recovery.retained && room.attempts.length===1 && room.attempts[0].state==='retainedDraft'")
      try await waitUntil(provider, "deliveries===0 && document.querySelector('textarea').value.includes('[TWOS handoff ')")
      _ = try await provider.evaluateJavaScript("submit.disabled=false;submit.removeAttribute('data-testid');submit.removeAttribute('aria-label');submit.textContent='';submit.type='submit';submit.form.onsubmit=e=>e.preventDefault();true")
      if scenario == "manual" {
        _ = try await provider.evaluateJavaScript("submit.click();input.remove();true")
      } else if scenario == "missing" {
        _ = try await provider.evaluateJavaScript("input.value='other draft';true")
        try await press("Check original conversation")
        try await waitUntil(team.web, "room.recovery.state==='retainedChanged' && !document.querySelector('#notice').innerText.includes('Send verified draft')")
        _ = try await provider.evaluateJavaScript("input.value='';true")
        try await press("Check original conversation")
        try await press("I have not sent it · restore draft")
        try await waitUntil(provider, "deliveries===0 && input.value.includes('[TWOS handoff ')")
      }
      try await press("Check original conversation")
      if scenario != "manual" {
        try await waitUntil(team.web, "room.recovery.state==='retainedExact'")
        try await waitUntil(provider, "deliveries===0")
        try await press("Send verified draft")
      }
    }
    try await waitUntil(team.web, "room.answers.length===1 && room.state==='completed' && room.queue.length===0")
    try await waitUntil(provider, "deliveries===1")
    if scenario == "richText" {
      try await waitUntil(provider, "(e=>e.getAttribute('spellcheck')==='true' && !e.hasAttribute('autocorrect') && !e.hasAttribute('writingsuggestions'))(document.querySelector('#prompt-textarea'))")
    }
    let record=try TeamWorkspace.readRecord(roomID,from:dir)
    if scenario == "foldedEcho" {try await waitUntil(provider, "expansions===1 && wrongClicks===0 && deliveries===1")}
    if scenario == "delayedEcho" {
      try await waitUntil(provider, "clicks===1 && deliveries===1")
      guard record.attempts[0].thread?.hasSuffix("/c/first-send-fixture")==true else {
        throw ProbeFailure(description:"Did not bind late echo to its provider conversation")
      }
    }
    guard record.attempts.count==1,record.conversation?.inputs.count==2,record.conversation?.skippedCopies?.count==1,
          record.attempts.first?.model==nil else { throw ProbeFailure(description:"Durable receipt mismatch") }
    if scenario == "multiround" {
      _ = try await provider.evaluateJavaScript("picker.textContent='GPT-6.2';true")
      _ = try await team.web.evaluateJavaScript("const m=document.getElementById('message');m.value='Second synthetic status request';m.dispatchEvent(new Event('input'));document.getElementById('send').click();true")
      try await waitUntil(team.web, "room.answers.length===2 && room.state==='completed' && room.queue.length===0")
      try await waitUntil(provider, "deliveries===2")
      let second = try TeamWorkspace.readRecord(roomID, from:dir)
      guard second.attempts.count==2, second.attempts[1].observedWebSelection=="GPT-6.2",
            second.attempts[0].id != second.attempts[1].id else { throw ProbeFailure(description:"Multi-round receipt mismatch") }
      print("PASS old Medium room, two completed user turns, unique receipts, updated model selection")
    }
    if scenario == "delayedRoute" {
      guard record.attempts[0].thread?.hasSuffix("/c/first-send-fixture")==true,
        record.milestones?.contains(where:{$0.state=="paused" && $0.afterAttempt==record.attempts[0].id}) != true else {
        throw ProbeFailure(description:"The original conversation needed manual reconciliation")
      }
      print("PASS confirmed exact echo, unloaded nodes, delayed official route, automatic completion, one click")
    }
    print("PASS guest with composer, visible sign-in, actual member window, website default, refresh without send, explicit continuation, one provider click, one matched reply, duplicate history preserved, unknown model retained")
    team.shutdown(); exit(0)
  } catch { print("FAILED",error);exit(1) }
}
app.run()
