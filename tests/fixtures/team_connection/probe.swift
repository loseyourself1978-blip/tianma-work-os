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
let member = TeamMember(role: "Planner", product: "ChatGPT", provider: "OpenAI", model: "", displayName: "Ada", duties: ["Planner"])
let folder = try NativeCodex.inspectDirectory(dir.path, isolated: true)
var restored = TeamRun(id: roomID, created: 1, goal: "Offline recovery fixture", csv: "", folder: folder, members: [member])
var conversation = TeamConversation()
for _ in 0..<2 {
  var draft = TeamDraft()
  draft.text = "Give the status of this synthetic fixture."
  try conversation.submit(draft, members: [member], language: "en")
}
restored.conversation = conversation; restored.state = "paused"; restored.reason = "reviewerUnavailable"; restored.next = "Planner"
let scenario = CommandLine.arguments[3]
if scenario == "uncertain" {
  restored.state = "running"
  let prompt = try restored.prompt(), a = try restored.begin(prompt)
  var receipt = WebHandoffReceipt(source: "team:" + roomID, message: a.id, text: prompt, hash: a.inputHash,
     provider: "ChatGPT", targetPane: 0, targetURL: TeamMember.homes["ChatGPT"]!, binding: roomID)
  receipt.mayHaveSent = true
  restored.attempts[0].web = receipt; restored.attempts[0].state = "unknown"
  restored.state = "paused"; restored.reason = "unconfirmed"
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
@MainActor func waitUntil(_ page: WKWebView, _ predicate: String) async throws {
  let limit = Date().addingTimeInterval(20)
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
      try await waitUntil(team.web, "room?.pending && !room.recovery.step && document.querySelector('#notice').innerText.includes('Reconcile')")
      try await press("Reconcile")
      try await waitUntil(team.web, "room.channelNotice==='reconciling' && !room.recovery.step && room.attempts.length===1")
      print("PASS uncertain receipt offered inspection only");team.shutdown();exit(0)
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
    guard let back = provider.window?.titlebarAccessoryViewControllers.compactMap({ $0.view as? NSButton })
      .first(where: { $0.title == "Back to chat · Check connection" }) else { throw ProbeFailure(description: "Missing return action") }
    back.performClick(nil)
    try await waitUntil(team.web, "room.recovery.state==='webReady' && room.inputs.length===2 && room.attempts.length===0")
    if ["retained", "manual", "missing"].contains(scenario) {
      _ = try await provider.evaluateJavaScript("const submit=document.querySelector('[data-testid=send-button]'); submit.disabled=true; true")
    }
    if scenario == "richText" {
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
    try await press("Continue once · skip duplicate copies")
    if ["retained", "manual", "missing"].contains(scenario) {
      try await waitUntil(team.web, "room.recovery.retained && room.attempts.length===1 && room.attempts[0].state==='retainedDraft'")
      try await waitUntil(provider, "deliveries===0 && document.querySelector('textarea').value.includes('[TWOS handoff ')")
      _ = try await provider.evaluateJavaScript("submit.disabled=false;submit.removeAttribute('data-testid');submit.removeAttribute('aria-label');submit.textContent='';submit.type='submit';submit.form.onsubmit=e=>e.preventDefault();true")
      if scenario == "manual" {
        _ = try await provider.evaluateJavaScript("submit.click();true")
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
    print("PASS guest with composer, visible sign-in, actual member window, website default, refresh without send, explicit continuation, one provider click, one matched reply, duplicate history preserved, unknown model retained")
    team.shutdown(); exit(0)
  } catch { print("FAILED",error);exit(1) }
}
app.run()
