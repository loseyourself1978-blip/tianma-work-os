import AppKit
import CryptoKit
import UniformTypeIdentifiers
import Darwin

struct WebTransferFile: Codable, Equatable {
    let id: String
    let name: String
    let mime: String
    let size: Int
    let hash: String
    let source: String
    static func read(_ url:URL) throws -> Data {
        guard url.standardizedFileURL == url.resolvingSymlinksInPath() else {throw CodexAttachmentFailure.unreadable}
        let fd=Darwin.open(url.path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC)
        guard fd>=0 else{throw CodexAttachmentFailure.unreadable};defer{Darwin.close(fd)}
        var st=stat();guard fstat(fd,&st)==0,st.st_mode&S_IFMT==S_IFREG,st.st_size>0,st.st_size<=8_000_000 else{throw CodexAttachmentFailure.tooLarge}
        var bytes=[UInt8](repeating:0,count:Int(st.st_size)),offset=0
        while offset<bytes.count {
            let remaining=bytes.count-offset
            let count=bytes.withUnsafeMutableBytes{Darwin.read(fd,$0.baseAddress!.advanced(by:offset),remaining)}
            guard count>0 else{throw CodexAttachmentFailure.unreadable};offset += count
        }
        return Data(bytes)
    }
}

// Scheduling facts only. Website content remains in the existing private
// handoff ledger; Nyra never receives this structure or any attachment bytes.
struct PairedDialogue: Codable {
    let id: String
    let providers: [String]
    var conversations: [String]
    let roles: [String]
    let firstText: String
    let maxExchanges: Int
    let duration: TimeInterval
    let createdAt: TimeInterval
    var state: String = "paused"
    var reason: String = ""
    var sentCount = 0
    var completedCount = 0
    var pendingID: String?
    var replyHashes: [String] = []
    var stopOnConcession = false
    var fileIDs: [String] = []
    var files: [WebTransferFile]?
    var untilStopped: Bool?
    var firstMessage: String?
    var firstHash: String?
    var deadline: TimeInterval { untilStopped == true ? .infinity : createdAt + duration }
    var roundLimitReached: Bool { untilStopped != true && completedCount >= maxExchanges }
    var progressLabel: String { untilStopped == true ? "\(completedCount)" : "\(completedCount)/\(maxExchanges)" }
    var nextTarget: Int { completedCount.isMultiple(of:2) ? 1 : 0 }
    var valid: Bool {
        providers.count==2 && Set(providers).count==2 && providers.allSatisfy{["ChatGPT","Claude","DeepSeek"].contains($0)} &&
        conversations.count==2 && roles.count==2 &&
        (untilStopped == true ? (maxExchanges==0 && duration==0) : ((2...100).contains(maxExchanges) && maxExchanges.isMultiple(of:2) && duration>0 && duration<=7200)) &&
        sentCount>=0 && completedCount>=0 && completedCount<=sentCount && (untilStopped == true || sentCount<=maxExchanges) &&
        createdAt.isFinite && duration.isFinite &&
        !firstText.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty && firstText.utf8.count<=150000 &&
        ["paused","running","stopped","finished"].contains(state)
    }
    static func concession(_ text: String) -> Bool {
        // Only an explicit standalone final statement from the current answer.
        // A quote, code block, historical citation or prose containing the word
        // cannot declare a winner or stop a discussion.
        var code = false, eligible: [String] = []
        for line in text.components(separatedBy:.newlines) {
            let s = line.trimmingCharacters(in:.whitespaces)
            if s.hasPrefix("```") || s.hasPrefix("~~~") { code.toggle(); continue }
            if code || s.hasPrefix(">") || s.hasPrefix("\"") || s.hasPrefix("“") || s.isEmpty { continue }
            eligible.append(s)
        }
        guard let last = eligible.last else { return false }
        return ["i concede", "i concede.", "我认输", "我认输。", "concede", "stalemate", "status: concede", "status: stalemate", "状态：认输", "状态：僵局"].contains(last.lowercased())
    }
}

struct PaneActivity {
    let session: String
    let task: String?
    let state: String
    let at: TimeInterval
    var evidence: String? = nil
    var reason: String = "OBSERVED_STATE"
    var fresh: Bool { (0..<8).contains(ProcessInfo.processInfo.systemUptime - at) }
    var wire: [String:Any] { ["state":fresh ? state : "activity_unknown","reason":fresh ? reason : "OBSERVATION_STALE","fresh":fresh] }
    static func observations(_ panes:[Int:PaneActivity]) -> [[String:Any]] {
        (0...1).map { index in
            var value=panes[index]?.wire ?? ["state":"activity_unknown","reason":"NO_OBSERVATION","fresh":false]
            value["side"]=index==0 ? "left" : "right";return value
        }
    }
    static func aggregate(_ panes: [Int:PaneActivity]) -> (state:String, side:String) {
        let work = (0...1).filter { panes[$0]?.fresh == true && panes[$0]?.state == "running" }
        if !work.isEmpty { return ("running",work.count == 2 ? "both" : work[0] == 0 ? "left" : "right") }
        let states = (0...1).map { panes[$0]?.fresh == true ? panes[$0]!.state : "activity_unknown" }
        for state in ["waiting_user","queued","activity_unknown","disconnected","failed","partial","cancelled","completed_unverified"] {
            if states.contains(state) { return (state,"both") }
        }
        if states.contains("verified_success") { return ("verified_success","both") }
        return ("idle","both")
    }
}

extension IntegratedWorkbench {
    func chooseWebFiles(_ side:Int) {
        guard dialogue?.state != "running" else {webPanes[side]?.showNotice("Pause automatic exchange before changing attachment scope.");return}
        let panel=NSOpenPanel();panel.canChooseDirectories=false;panel.allowsMultipleSelection=true
        panel.allowedContentTypes=[.plainText,.png,.jpeg,.pdf];panel.allowsOtherFileTypes=true
        panel.message=translate("Select only files authorized for this handoff. Selection does not upload them. Supported: TXT, Markdown, PNG/JPEG, simple PDF; 8 MB per file, 12 MB total.")
        guard let window=window else{return}
        panel.beginSheetModal(for:window){[weak self] answer in
            guard answer == .OK,let self=self else{return}
            do {
                let root=self.preferences.appendingPathComponent("web-transfer-files");try NativeWorkbench.safeDirectory(root)
                var chosen:[WebTransferFile]=[],total=0
                for url in panel.urls {
                    let ext=url.pathExtension.lowercased(),mime:[String:String]=["txt":"text/plain","md":"text/markdown","png":"image/png","jpg":"image/jpeg","jpeg":"image/jpeg","pdf":"application/pdf"]
                    guard let type=mime[ext] else{throw CodexAttachmentFailure.unsupported}
                    let bytes=try WebTransferFile.read(url);total += bytes.count
                    guard total<=12_000_000,chosen.count<8 else{throw CodexAttachmentFailure.tooLarge}
                    // Validate declared content locally; transmit the original
                    // bytes, never silently convert PDF into extracted text.
                    let parsed = try CodexAttachmentParser.parse(name:url.lastPathComponent,bytes:bytes,scratch:root)
                    if type.hasPrefix("image/"),parsed.mime != type {throw CodexAttachmentFailure.malformed}
                    let file=WebTransferFile(id:UUID().uuidString,name:url.lastPathComponent,mime:type,size:bytes.count,hash:NativeCodex.digest(bytes),source:url.lastPathComponent)
                    let target=root.appendingPathComponent(file.id)
                    try bytes.write(to:target,options:.atomic);try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:target.path)
                    chosen.append(file)
                }
                self.webFileSelections[side]=chosen;try self.saveWebFileSelections();self.updateWebFileLabel(side)
            } catch {
                let message=(error as? CodexAttachmentFailure) == .unsupported ? "Website handoff supports TXT, Markdown, PNG/JPEG and simple PDF. This file was not attached or uploaded." : ((error as? CodexAttachmentFailure)?.message ?? "The selected files could not be attached. Nothing was uploaded.")
                self.webPanes[side]?.showNotice(message)
            }
        }
    }
    func updateWebFileLabel(_ side:Int) {
        let files=webFileSelections[side] ?? []
        webPanes[side]?.setFileSelectionCount(files.count)
        if !files.isEmpty {webPanes[side]?.showNotice(translate("Selected files · not uploaded")+": "+files.map{$0.name+" · \($0.size) B"}.joined(separator:", "))}
    }
    func clearWebFiles(_ side:Int) {
        guard dialogue?.state != "running" else{webPanes[side]?.showNotice("Pause automatic exchange before changing attachment scope.");return}
        webFileSelections[side]=[];try? saveWebFileSelections();updateWebFileLabel(side)
        webPanes[side]?.showNotice("Attachment selection removed. Website drafts and previous handoffs are unchanged.")
    }
    func saveWebFileSelections() throws {
        let file=preferences.appendingPathComponent("web-transfer-selections.json")
        try JSONEncoder().encode(webFileSelections).write(to:file,options:.atomic)
        try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:file.path)
    }
    func payloadFiles(_ files:[WebTransferFile]) throws -> [[String:Any]] {
        guard files.count<=8,files.reduce(0,{$0+$1.size})<=12_000_000 else{throw CodexAttachmentFailure.tooLarge}
        return try files.map { file in
            guard UUID(uuidString:file.id) != nil else{throw CodexAttachmentFailure.unreadable}
            let bytes=try WebTransferFile.read(preferences.appendingPathComponent("web-transfer-files").appendingPathComponent(file.id))
            guard bytes.count==file.size,NativeCodex.digest(bytes)==file.hash else{throw CodexAttachmentFailure.unreadable}
            return ["id":file.id,"name":file.name,"mime":file.mime,"size":file.size,"hash":file.hash,"base64":bytes.base64EncodedString()]
        }
    }
    @objc func showDialogue() {
        if dialogueWindow == nil {
            let w = NSWindow(contentRect:NSRect(x:0,y:0,width:720,height:730),styleMask:[.titled,.closable,.resizable],backing:.buffered,defer:false)
            w.isReleasedWhenClosed=false;w.delegate=self;dialogueWindow=w
            let status=NSTextField(wrappingLabelWithString:"");dialogueStatus=status
            let explain=NSTextField(wrappingLabelWithString:translate("Automatic exchange is off by default. Only these two conversations, roles, selected files and complete replies are shared. No file execution, commands, approvals or Git rights are granted."))
            let roleA=NSTextField(),roleB=NSTextField();dialogueRoles=[roleA,roleB]
            roleA.placeholderString=translate("Left participant role");roleB.placeholderString=translate("Right participant role")
            let text=NSTextView(frame:NSRect(x:0,y:0,width:680,height:160));text.font = .systemFont(ofSize:14);dialogueText=text
            text.minSize=NSSize(width:0,height:140);text.isHorizontallyResizable=false;text.textContainer?.widthTracksTextView=true
            text.setAccessibilityLabel(translate("First instruction · sent to the right participant"))
            let scroll=NSScrollView();scroll.documentView=text;scroll.hasVerticalScroller=true;text.isVerticallyResizable=true;text.autoresizingMask=[.width]
            let rounds=NSTextField(string:"3"),minutes=NSTextField(string:"15");dialogueRounds=rounds;dialogueMinutes=minutes
            // Both budgets remain editable at the initial window width. Do
            // not let one text field take all free space and collapse the other.
            rounds.widthAnchor.constraint(equalToConstant:72).isActive=true
            minutes.widthAnchor.constraint(equalToConstant:72).isActive=true
            rounds.setAccessibilityLabel(translate("Round trips (1–50)"))
            minutes.setAccessibilityLabel(translate("Minutes (1–120)"))
            let budgets=NSStackView(views:[NSTextField(labelWithString:translate("Round trips (1–50)")),rounds,NSTextField(labelWithString:translate("Minutes (1–120)")),minutes]);budgets.spacing=8
            let unlimited=NSButton(checkboxWithTitle:translate("Until you stop · no round or time limit"),target:self,action:#selector(dialogueBudgetChanged));dialogueUntilStopped=unlimited
            let seed=NSButton(title:translate("Use latest complete reply from the left"),target:self,action:#selector(selectDialogueSeed))
            let concession=NSButton(checkboxWithTitle:translate("Stop at an explicit final concession"),target:nil,action:nil);dialogueConcession=concession
            let start=NSButton(title:translate("Start automatic exchange"),target:self,action:#selector(startDialogue))
            let pause=NSButton(title:translate("Pause"),target:self,action:#selector(pauseDialogueAction))
            let resume=NSButton(title:translate("Continue"),target:self,action:#selector(resumeDialogue))
            let stop=NSButton(title:translate("Stop future exchanges"),target:self,action:#selector(stopDialogue))
            let buttons=NSStackView(views:[start,pause,resume,stop]);buttons.spacing=8
            let layout=NSStackView(views:[explain,status,roleA,roleB,NSTextField(labelWithString:translate("First instruction · sent to the right participant")),scroll,seed,unlimited,budgets,concession,buttons]);layout.orientation = .vertical;layout.alignment = .leading;layout.spacing=12;layout.translatesAutoresizingMaskIntoConstraints=false
            w.contentView!.addSubview(layout)
            NSLayoutConstraint.activate([layout.leadingAnchor.constraint(equalTo:w.contentView!.leadingAnchor,constant:16),layout.trailingAnchor.constraint(equalTo:w.contentView!.trailingAnchor,constant:-16),layout.topAnchor.constraint(equalTo:w.contentView!.topAnchor,constant:16),layout.bottomAnchor.constraint(equalTo:w.contentView!.bottomAnchor,constant:-16),scroll.widthAnchor.constraint(equalTo:layout.widthAnchor),scroll.heightAnchor.constraint(greaterThanOrEqualToConstant:140),roleA.widthAnchor.constraint(equalTo:layout.widthAnchor),roleB.widthAnchor.constraint(equalTo:layout.widthAnchor),status.widthAnchor.constraint(equalTo:layout.widthAnchor),explain.widthAnchor.constraint(equalTo:layout.widthAnchor)])
        }
        dialogueWindow?.title=translate("Automatic exchange");refreshDialogueUI();dialogueWindow?.center();dialogueWindow?.makeKeyAndOrderFront(nil)
    }
    func refreshDialogueUI() {
        if let view=dialogueWindow?.contentView {
            func walk(_ node:NSView) {
                if let button=node as? NSButton {button.title=translate(button.title)}
                if let label=node as? NSTextField,!label.isEditable {label.stringValue=translate(label.stringValue)}
                if node is NSTextView {return};node.subviews.forEach(walk)
            };walk(view)
            dialogueRoles.first?.placeholderString=translate("Left participant role")
            dialogueRoles.last?.placeholderString=translate("Right participant role")
            dialogueRounds?.setAccessibilityLabel(translate("Round trips (1–50)"))
            dialogueMinutes?.setAccessibilityLabel(translate("Minutes (1–120)"))
        }
        let targets=(0...1).map { kinds[$0] + " · " + (webPanes[$0].flatMap { NativeWorkbench.restorableURL($0.web.url,service:$0.serviceHome) }?.absoluteString ?? translate("Not ready")) }.joined(separator:"\n↔ ")
        let nextFiles=(webFileSelections[0] ?? [])+(webFileSelections[1] ?? [])
        func fileList(_ files:[WebTransferFile],_ label:String)->String {
            "\n"+translate(label)+": "+(files.isEmpty ? "—" : files.map{$0.name+" ["+$0.hash.prefix(12)+"]"}.joined(separator:", "))
        }
        // A saved terminal exchange is history, not the next Start's scope.
        // Paused exchanges retain their authorized list independently of new
        // selections; Continue must never silently adopt those selections.
        let continuing=["running","paused"].contains(dialogue?.state ?? "")
        var fileLabel=continuing ? fileList(dialogue?.files ?? [],"Authorized files for the saved exchange") : ""
        if dialogue?.state != "running" { fileLabel += fileList(nextFiles,"Files selected for a new exchange") }
        if let d=dialogue {
            let pending=d.pendingID.flatMap { id in webTransfers.first{$0.id==id} }
            let waiting=pending.map { "\n"+translate("Waiting for")+": "+$0.provider+" · "+translate($0.statusLabel) } ?? ""
            let bound=d.providers.enumerated().map { $0.element+" · "+d.conversations[$0.offset] }.joined(separator:"\n↔ ")
            dialogueStatus?.stringValue=translate("Current panes")+":\n"+targets+"\n"+translate("Authorized conversations")+":\n"+bound + "\n" + translate(d.state) + " · " + d.progressLabel + " " + translate("directional exchanges") + " · " + translate(d.reason) + waiting + fileLabel
        } else { dialogueStatus?.stringValue=targets + "\n" + translate("Off · nothing is sent until you start") + fileLabel }
        dialogueButton.title=translate("Automatic exchange") + (dialogue?.state == "running" ? " · " + dialogue!.progressLabel : "")
    }
    @discardableResult func saveDialogue() -> Bool {
        do {
            try NativeWorkbench.safeDirectory(preferences)
            if let value=dialogue {
                let file=preferences.appendingPathComponent("paired-dialogue.json")
                try JSONEncoder().encode(value).write(to:file,options:.atomic)
                try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:file.path)
            }
            refreshDialogueUI();return true
        } catch { dialogue?.state="paused";dialogue?.reason="Could not save exchange state. No next message will be sent.";refreshDialogueUI();return false }
    }
    func pauseDialogue(_ reason: String) {
        guard dialogue?.state == "running" else { return }
        invalidateDialogueSendLease()
        dialogue?.state="paused";dialogue?.reason=reason;_ = saveDialogue()
    }
    @objc func pauseDialogueAction() { pauseDialogue("Paused by you. The provider may finish its current reply; no next message is sent.") }
    @objc func stopDialogue() { stopDialogueWithReason("Future exchanges stopped. This does not cancel a provider's current generation.") }
    func stopDialogueWithReason(_ reason:String) {
        dialogueStartToken=nil;dialogueStartPending=false
        guard dialogue != nil else{return}
        // Latch before invalidating asynchronous leases or processing a reply.
        // A late callback can update its receipt, never schedule the next turn.
        dialogue?.state="stopped";dialogue?.reason=reason;_ = saveDialogue()
        invalidateDialogueSendLease()
    }
    func stopDialogueFromPane(_ index:Int,source:URL) {
        guard let d=dialogue,["running","paused"].contains(d.state), (0...1).contains(index), kinds[index]==d.providers[index] else{return}
        // Revocation is safe even during /new -> conversation navigation.
        // The native bridge already binds the trusted click to this actual pane.
        stopDialogueWithReason(index==0 ? "Left participant stopped · future exchanges cancelled" : "Right participant stopped · future exchanges cancelled")
    }
    func invalidateDialogueSendLease() {
        guard let d=dialogue else{return}
        for i in webTransfers.indices where webTransfers[i].dialogueID==d.id {
            let id=webTransfers[i].id
            activeWebQueues.remove(id);transferTimers.removeValue(forKey:id)?.invalidate()
            if webTransfers[i].mayHaveSent != true,["preparing","queued","queue_paused","busy"].contains(webTransfers[i].state) {
                webTransfers[i].state=d.state=="stopped" ? "cancelled" : "queue_paused"
            }
            if webTransfers[i].state=="sending" {
                webPanes[webTransfers[i].targetPane]?.web.evaluateJavaScript("window.twosTransferLease = crypto.randomUUID()",in:nil,in:NativeWorkbench.handoffWorld,completionHandler:nil)
            }
        }
        _ = persistWebTransfers()
    }
    @objc func dialogueBudgetChanged() {
        let limited=dialogueUntilStopped?.state != .on
        dialogueRounds?.isEnabled=limited;dialogueMinutes?.isEnabled=limited
    }
    @objc func selectDialogueSeed() {
        guard dialogue?.state != "running",let pane=webPanes[0],let source=NativeWorkbench.restorableURL(pane.web.url,service:pane.serviceHome) else{return}
        let binding=routeSignature(0)
        pane.providerSnapshot(includeReply:true,latestOnly:true) { [weak self,weak pane] result in
            guard let self=self,let pane=pane,self.webPanes[0] === pane,self.dialogue?.state != "running",
                  NativeWorkbench.restorableURL(pane.web.url,service:pane.serviceHome)==source,binding==self.routeSignature(0) else{return}
            guard result["state"] as? String=="reply",let text=result["text"] as? String,let message=result["message"] as? String else {
                self.showDialogueNotice("No complete first reply is available. Nothing was sent. " + (result["reason"] as? String ?? ""));return
            }
            self.dialogueText?.string=text
            self.dialogueSeed=(source.absoluteString,message,NativeCodex.digest(Data(text.utf8)))
            self.showDialogueNotice("Latest complete reply selected. Start rechecks its identity and both destinations; nothing has been sent.")
        }
    }
    func dialogueTargetsMatch(_ value:PairedDialogue) -> Bool {
        (0...1).allSatisfy { index in
            guard kinds[index] == value.providers[index], let pane=webPanes[index] else { return false }
            let actual=NativeWorkbench.restorableURL(pane.web.url,service:pane.serviceHome)?.absoluteString
            if actual == value.conversations[index] { return true }
            // Only the exact pending receipt may prove the new conversation URL
            // after a first send. Merely navigating elsewhere is not a rebind.
            if let id=value.pendingID, let r=webTransfers.first(where:{$0.id==id}), r.targetPane==index,
               r.resolvedURL==actual, ["sent","reply"].contains(r.state) { return true }
            return false
        }
    }
    @objc func startDialogue() {
        guard !dialogueStartPending, dialogue?.state != "running", dialogue?.pendingID == nil || ["finished","stopped"].contains(dialogue?.state ?? "") else { showDialogueNotice("Resolve or resume the saved exchange before starting another.");return }
        if let pending=dialogue?.pendingID {
            guard let receipt=webTransfers.first(where:{$0.id==pending}),receipt.mayHaveSent != true || ["reply","generation_stopped"].contains(receipt.state) else {
                showDialogueNotice("The previous submission still needs reconciliation. Check delivery before starting another exchange.");return
            }
        }
        guard kinds.allSatisfy({["ChatGPT","Claude","DeepSeek"].contains($0)}), kinds[0] != kinds[1],
              let a=webPanes[0],let b=webPanes[1],let au=NativeWorkbench.restorableURL(a.web.url,service:a.serviceHome),let bu=NativeWorkbench.restorableURL(b.web.url,service:b.serviceHome),
              let rounds=Int(dialogueRounds?.stringValue ?? ""),let minutes=Int(dialogueMinutes?.stringValue ?? ""),
              dialogueUntilStopped?.state == .on || ((1...50).contains(rounds) && (1...120).contains(minutes)),
              let text=dialogueText?.string,!text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty,text.utf8.count<=150000 else { showDialogueNotice("Select two different supported website conversations and valid round/time budgets. No task was sent.");return }
        let files=(webFileSelections[0] ?? [])+(webFileSelections[1] ?? [])
        guard (try? payloadFiles(files)) != nil else{showDialogueNotice("An attachment is missing, changed or too large. Nothing was sent.");return}
        let value=PairedDialogue(id:UUID().uuidString,providers:kinds,conversations:[au.absoluteString,bu.absoluteString],roles:dialogueRoles.map(\.stringValue),firstText:text,maxExchanges:dialogueUntilStopped?.state == .on ? 0 : rounds*2,duration:dialogueUntilStopped?.state == .on ? 0 : Double(minutes)*60,createdAt:Date().timeIntervalSince1970,state:"running",stopOnConcession:dialogueConcession?.state == .on,fileIDs:files.map(\.id),files:files,untilStopped:dialogueUntilStopped?.state == .on,firstMessage:dialogueSeed?.message,firstHash:dialogueSeed?.hash)
        guard value.valid else {showDialogueNotice("The automatic exchange configuration is invalid. Nothing was sent.");return}
        let binding=routeSignature(0),startToken=UUID().uuidString
        dialogueStartToken=startToken
        let launch = { [weak self] in
            guard let self=self,self.dialogueStartToken==startToken,self.dialogue?.state != "running",binding==self.routeSignature(0),self.dialogueTargetsMatch(value) else{return}
            self.dialogueStartToken=nil;self.dialogueStartPending=false;self.dialogue=value
            guard self.saveDialogue() else{return};self.tickDialogue()
        }
        if let seed=dialogueSeed {
            guard seed.source==au.absoluteString,seed.hash==NativeCodex.digest(Data(text.utf8)) else {
                showDialogueNotice("The selected first reply or conversation changed. Select the latest complete reply again. Nothing was sent.");return
            }
            dialogueStartPending=true
            a.providerSnapshot(includeReply:true,latestOnly:true) { [weak self] result in
                guard let self=self,self.dialogueStartToken==startToken else{return};self.dialogueStartPending=false
                guard result["state"] as? String=="reply",result["message"] as? String==seed.message,
                      (result["text"] as? String).map({NativeCodex.digest(Data($0.utf8))})==seed.hash else {
                    self.showDialogueNotice("The selected first reply changed or is incomplete. Nothing was sent.");return
                }
                launch()
            }
        } else { launch() }
    }
    func showDialogueNotice(_ text:String) { dialogueStatus?.stringValue=translate(text) }
    @objc func resumeDialogue() {
        guard let d=dialogue,d.state=="paused",dialogueTargetsMatch(d) else { showDialogueNotice("Open both bound conversations before continuing. Nothing was sent.");return }
        guard Date().timeIntervalSince1970<d.deadline else { showDialogueNotice("The authorized time budget has ended. Start a new exchange with a new budget; the old one will not replay.");return }
        dialogue?.state="running";dialogue?.reason="Reconcile the last receipt before any new send"
        guard saveDialogue() else{return}
        if let id=d.pendingID,let i=webTransfers.firstIndex(where:{$0.id==id}),let target=webPanes[webTransfers[i].targetPane] {
            if webTransfers[i].mayHaveSent == true {inspectWebTransfer(id,target:target)}
            else if ["queue_paused","queued","preparing"].contains(webTransfers[i].state) {
                webTransfers[i].state="preparing";if persistWebTransfers(){submitWebTransfer(id,target:target)}
            }
        } else {tickDialogue()}
    }
    func tickDialogue() {
        guard let d=dialogue,d.state=="running",!dialogueTickInFlight else { return }
        guard Date().timeIntervalSince1970<d.deadline else { pauseDialogue("Time budget reached");return }
        // A first website send may replace /new with its new conversation URL
        // before the exact marked-message receipt resolves. Wait for that one
        // in-flight call; this does not authorize a new target or another send.
        // Its response must still prove the full body and bind resolvedURL.
        // Restart turns persisted `sending` into `unknown`, never an auto retry.
        if let id=d.pendingID,webTransfers.first(where:{$0.id==id})?.state=="sending" {return}
        guard dialogueTargetsMatch(d) else {
            // During a first conversation transition WebKit can temporarily
            // expose no restorable URL even though it already echoed our exact
            // submission. Wait read-only for at most five regular ticks. Do not
            // inspect an unapproved location, send again, or rebind from a URL.
            if let id=d.pendingID,let i=webTransfers.firstIndex(where:{$0.id==id}) {
                let r=webTransfers[i],side=r.targetPane,other=1-side
                if r.mayHaveSent == true,["sent","reply","unknown"].contains(r.state),
                   r.resolvedURL == nil || r.resolvedURL == r.targetURL,
                   kinds[side]==r.provider,kinds[other]==d.providers[other],
                   let original=URL(string:r.targetURL),["","/","/new"].contains(original.path),
                   let pane=webPanes[side],let peer=webPanes[other],
                   NativeWorkbench.restorableURL(peer.web.url,service:peer.serviceHome)?.absoluteString==d.conversations[other],
                   NativeWorkbench.restorableURL(pane.web.url,service:pane.serviceHome)==nil,
                   pane.web.url == nil || (pane.web.url?.scheme==original.scheme && pane.web.url?.host==original.host && pane.web.url?.port==original.port) {
                    let attempts=dialogueNavigationReads[id,default:0]
                    if attempts<5 {
                        dialogueNavigationReads[id]=attempts+1
                        webTransfers[i].inspection="FIRST_CONVERSATION_ADDRESS_PENDING · read-only wait \(attempts+1)/5"
                        webTransfers[i].inspectedAt=Date().timeIntervalSince1970
                        _ = persistWebTransfers();return
                    }
                }
            }
            // Some providers acknowledge the exact user message on /new before
            // assigning its conversation URL. Reconcile that one pending first
            // send read-only; never treat navigation itself as authorization.
            if let id=d.pendingID,let r=webTransfers.first(where:{$0.id==id}),
               let pane=webPanes[r.targetPane],let other=webPanes[1-r.targetPane],canInspectCurrentTarget(r),
               kinds[1-r.targetPane]==d.providers[1-r.targetPane],
               NativeWorkbench.restorableURL(other.web.url,service:other.serviceHome)?.absoluteString==d.conversations[1-r.targetPane] {
                if inspectionsInFlight.contains(id) {return}
                // URL assignment and message hydration are separate website
                // events. A bounded read-only reconciliation window may wait
                // for the exact receipt; it never resends or grants a new URL.
                let attempts=dialogueNavigationReads[id,default:0]
                guard attempts<5 else {
                    pauseDialogue("A participant or conversation changed. Restore the bound conversations before continuing.");return
                }
                dialogueNavigationReads[id]=attempts+1
                dialogueTickInFlight=true;inspectionsInFlight.insert(id)
                pane.webTransfer(r.request(inspectOnly:true)) { [weak self] response in
                    guard let self=self else{return};self.dialogueTickInFlight=false;self.inspectionsInFlight.remove(id)
                    guard self.dialogue?.id==d.id,self.dialogue?.state=="running",self.dialogue?.pendingID==id else{return}
                    if let i=self.webTransfers.firstIndex(where:{$0.id==id}) {
                        self.webTransfers[i].inspection="FIRST_CONVERSATION_RECONCILIATION · " + (response["state"] as? String ?? "unknown") + (response["reason"].map {" · \($0)"} ?? "")
                        self.webTransfers[i].inspectedAt=Date().timeIntervalSince1970
                    }
                    self.applyWebResponse(id,response:response)
                    if self.dialogueTargetsMatch(d) {self.dialogueNavigationReads.removeValue(forKey:id);self.tickDialogue()}
                    // Otherwise wait for the next regular tick, within five
                    // reads. Changed/missing bodies cannot advance the run.
                }
                return
            }
            if let id=d.pendingID,let i=webTransfers.firstIndex(where:{$0.id==id}) {
                let r=webTransfers[i],p=r.targetPane,other=1-p
                let actual=webPanes[p].flatMap {NativeWorkbench.restorableURL($0.web.url,service:$0.serviceHome)}
                let peer=webPanes[other].flatMap {NativeWorkbench.restorableURL($0.web.url,service:$0.serviceHome)}
                // Bounded, content-free evidence explains why no reconciliation
                // was allowed. Do not persist URLs, drafts or account details.
                let firstRoot=["","/","/new"].contains(URL(string:r.targetURL)?.path ?? "invalid")
                webTransfers[i].inspection="TARGET_RECONCILIATION_INELIGIBLE · state=\(r.state) · mayHaveSent=\(r.mayHaveSent == true) · sameProvider=\(kinds[p]==r.provider) · sourceUnchanged=\(peer?.absoluteString==d.conversations[other]) · targetRestorable=\(actual != nil) · firstRoot=\(firstRoot) · inspectable=\(canInspectCurrentTarget(r))"
                webTransfers[i].inspectedAt=Date().timeIntervalSince1970
            }
            pauseDialogue("A participant or conversation changed. Restore the bound conversations before continuing.");return
        }
        if let id=d.pendingID {
            guard let r=webTransfers.first(where:{$0.id==id}), let pane=webPanes[r.targetPane] else { pauseDialogue("Pending receipt is missing. Nothing will be resent.");return }
            if inspectionsInFlight.contains(id) || r.state=="sending" {return}
            guard !["login","verification","draft","draft_conflict","unsupported","not_loaded","target_changed","queue_paused","unknown","provider_limited","cancelled","generation_stopped"].contains(r.state) else { pauseDialogue("Delivery or input needs verification. Check the pending receipt; no blind resend.");return }
            if r.state != "reply" { inspectWebTransfer(id,target:pane);return }
            guard let reply=r.result,!reply.isEmpty else { pauseDialogue("Completed reply is unavailable");return }
            dialogueTickInFlight=true
            pane.webTransfer(r.request(inspectOnly:true)) { [weak self] response in
                guard let self=self else{return};self.dialogueTickInFlight=false
                guard self.dialogue?.id==d.id,self.dialogue?.state=="running",self.dialogue?.pendingID==id else{return}
                guard response["state"] as? String=="reply",response["reply"] as? String==reply,self.dialogueTargetsMatch(d) else { self.pauseDialogue("The complete reply changed or could not be reconciled");return }
                let hash=NativeCodex.digest(Data(reply.utf8))
                guard !d.replyHashes.contains(hash) else { self.pauseDialogue("Repeated output detected");return }
                self.dialogue?.replyHashes.append(hash);self.dialogue?.completedCount += 1;self.dialogue?.pendingID=nil
                self.dialogue?.conversations[r.targetPane]=r.resolvedURL ?? r.targetURL
                if self.dialogue!.roundLimitReached || (d.stopOnConcession && PairedDialogue.concession(reply)) {
                    let reason=self.dialogue!.roundLimitReached ? "Authorized round budget completed" : "Current participant supplied an explicit final CONCEDE or STALEMATE statement"
                    self.dialogue?.state="finished";self.dialogue?.reason=reason
                }
                // Persist the completed turn and next sequence before dispatch.
                if self.saveDialogue(){self.tickDialogue()}
            }
            return
        }
        let targetIndex=d.nextTarget,sourceIndex=1-targetIndex
        guard let pane=webPanes[targetIndex] else{return}
        let previous=webTransfers.last(where:{$0.dialogueID==d.id && $0.state=="reply"})
        let body=d.completedCount==0 ? d.firstText : previous?.result ?? ""
        guard !body.isEmpty else {pauseDialogue("No complete reply is available");return}
        let text=(d.roles[targetIndex].isEmpty ? "" : "Participant role / 参与者角色:\n"+d.roles[targetIndex]+"\n\n")+body
        guard text.utf8.count<=200000 else{pauseDialogue("Reply exceeds the supported transfer size");return}
        let record=WebHandoffReceipt(source:d.conversations[sourceIndex],message:"dialogue:\(d.id):\(d.completedCount)",text:text,hash:NativeCodex.digest(Data(text.utf8)),provider:d.providers[targetIndex],targetPane:targetIndex,targetURL:d.conversations[targetIndex],binding:routeSignature(sourceIndex),dialogueID:d.id,files:d.files ?? [])
        webTransfers.append(record)
        guard persistWebTransfers() else {pauseDialogue("Could not save handoff intent");return}
        dialogue?.pendingID=record.id;dialogue?.sentCount += 1
        guard saveDialogue() else{return}
        submitWebTransfer(record.id,target:pane)
    }
}
