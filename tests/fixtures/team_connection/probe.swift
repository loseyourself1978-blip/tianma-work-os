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
let member = TeamMember(role: "Planner", product: "ChatGPT", provider: "OpenAI", model: scenario == "multiround" ? "Medium" : (scenario == "mismatch" ? "GPT-6.0" : ""), displayName: "Ada", duties: ["Planner"])
let folder = try NativeCodex.inspectDirectory(dir.path, isolated: true)
var restored = TeamRun(id: roomID, created: 1, goal: "Offline recovery fixture", csv: "", folder: folder, members: [member])
var conversation = TeamConversation()
for _ in 0..<2 {
  var draft = TeamDraft()
  draft.text = "Give the status of this synthetic fixture."
  try conversation.submit(draft, members: [member], language: "en")
}
restored.conversation = conversation; restored.state = "paused"; restored.reason = "reviewerUnavailable"; restored.next = "Planner"
if scenario == "uncertain" {
  restored.state = "running"
  let prompt = try restored.prompt(), a = try restored.begin(prompt)
  var receipt = WebHandoffReceipt(source: "team:" + roomID, message: a.id, text: prompt, hash: a.inputHash,
     provider: "ChatGPT", targetPane: 0, targetURL: TeamMember.homes["ChatGPT"]!, binding: roomID)
  receipt.mayHaveSent = true
  restored.attempts[0].web = receipt; restored.attempts[0].state = "unknown"
  restored.state = "paused"; restored.reason = "unconfirmed"
}
if scenario == "timeoutBoundary" {
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
    if scenario == "uncertain" {
      try await waitUntil(team.web, "room?.pending && room.recovery.uncertain")
      try await press("Open member window")
      guard let provider = NSApp.windows.first(where: { $0.title.contains("Ada") && $0.title.contains("ChatGPT") }).flatMap({webView($0.contentView)}) else { throw ProbeFailure(description:"Missing original member window") }
      try await waitUntil(provider, "Boolean(document.querySelector('[data-testid=login-button]'))")
      _ = try await provider.evaluateJavaScript("document.querySelector('[data-testid=login-button]').click();true")
      try await press("Check original conversation")
      try await waitUntil(team.web, "room.recovery.state==='retainedEmpty' && document.querySelector('#notice').innerText.includes('composer is empty')")
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
    back.performClick(nil)
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
    if scenario == "prepareError" {
      let _: Any = try await withCheckedThrowingContinuation { continuation in
        provider.callAsyncJavaScript("document.execCommand=()=>{throw new Error('offline edit failure')};return true",
          arguments:[:],in:nil,in:NativeWorkbench.handoffWorld) { continuation.resume(with:$0) }
      }
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
