import AppKit
import WebKit
import CryptoKit
import Security
import Darwin

// A single, pull-only local snapshot. The endpoint is not a command channel.
// Nyra's consumer is maintained separately; hiding/quitting it never affects work.
final class NyraStatusProducer {
    static let schemaVersion = "twos.nyra.status.v4"
    static let schemaSHA256 = "4e7d9433de4c807eb0e1e7f3a4ae51c3afd7a582769ba02fe02e43169a9e4226"
    static let states: Set<String> = ["idle", "queued", "running", "waiting_user", "partial", "failed", "completed_unverified", "verified_success", "cancelled", "disconnected", "activity_unknown"]
    let instance = UUID().uuidString
    let directory: URL
    let helper: URL
    private var socketFD: Int32 = -1
    private var socketSource: DispatchSourceRead?
    let socketQueue = DispatchQueue(label: "com.tianma.nyra.readonly-peer", qos: .utility)
    private let snapshotLock = NSLock()
    private var wireSnapshot = Data()
    private var socketDirectory: URL?
    private(set) var sequence: UInt64 = 0
    private(set) var endpointError: String?
    private var current: [String: Any] = [:]
    private var terminalTasks: [String: (state: String, source: String, evidence: String?)] = [:]
    private var authorizedStandalone: (path:String, hash:Data)?
    private var standaloneControls = false
    private var verifiedPeers: [pid_t:(stamp:String,at:Double)] = [:]
    var controlServer: NyraControlServer?
    var focusServer: NyraControlServer?
    var controlHandler: (([String:Any], @escaping ([String:Any])->Void)->Void)?
    init(directory: URL, helper: URL) {
        self.directory = directory; self.helper = helper
        do {
            try NativeWorkbench.safeDirectory(directory)
            let attrs = try nativePathMetadata(directory.path)
            guard attrs.st_uid == getuid(), attrs.st_mode & 0o777 == 0o700 else { throw CocoaError(.fileWriteNoPermission) }
            if let saved=NativeNyra.readVisibility(directory.appendingPathComponent("authorized-consumer.json")),
               let path=saved["path"] as? String,let encoded=saved["hash"] as? String,let hash=Data(base64Encoded:encoded) {authorizedStandalone=(path,hash);standaloneControls=saved["userControls"] as? Bool == true}
            // No state/body on disk. An endpoint is a capability locator, not
            // authorization: every connection is separately authenticated.
            // AF_UNIX avoids a public/loopback port and carries peer credentials.
            // A short private directory avoids sockaddr_un's 104-byte path limit.
            let root = URL(fileURLWithPath: "/private/tmp/twos-nyra-status-" + instance)
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
            socketDirectory = root
            let path = root.appendingPathComponent("status.sock").path
            socketFD = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
            guard socketFD >= 0 else { throw CocoaError(.fileWriteUnknown) }
            var address = sockaddr_un(); address.sun_family = sa_family_t(AF_UNIX)
            let count = path.utf8.count + 1
            guard count <= MemoryLayout.size(ofValue: address.sun_path) else { throw CocoaError(.fileWriteInvalidFileName) }
            withUnsafeMutableBytes(of: &address.sun_path) { bytes in
                path.utf8CString.withUnsafeBytes { bytes.copyMemory(from: $0) }
            }
            address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
            let bound = withUnsafePointer(to: &address) { pointer in
                pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(socketFD, $0, socklen_t(MemoryLayout<sockaddr_un>.size)) }
            }
            guard bound == 0, chmod(path, 0o600) == 0, listen(socketFD, 4) == 0,
                  fcntl(socketFD, F_SETFL, O_NONBLOCK) == 0 else { throw CocoaError(.fileWriteUnknown) }
            let file = directory.appendingPathComponent("endpoint.json")
            let bytes = try JSONSerialization.data(withJSONObject: ["transport":"unix_snapshot_v1", "socket":path, "producer_instance_id":instance, "schema_version":Self.schemaVersion, "schema_sha256":Self.schemaSHA256, "control_protocol":"twos.nyra.control.v1", "control_socket":root.appendingPathComponent("control.sock").path, "focus_protocol":"twos.nyra.focus.v1", "focus_socket":root.appendingPathComponent("focus.sock").path])
            try bytes.write(to: file, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
            let source = DispatchSource.makeReadSource(fileDescriptor: socketFD, queue: socketQueue)
            source.setEventHandler { [weak self] in self?.acceptSnapshots() }
            socketSource = source; source.resume()
            // Host focus is independent of task inspection, drafts and grants.
            // It retains the same signed same-user peer identity checks, and
            // cannot accept a task target or a mutation on this socket.
            focusServer = try NyraControlServer(root:root,instance:instance,focusOnly:true,authenticate:{[weak self] pid,uid,method in
                method=="focus" && self?.accepts(pid:pid,uid:uid)==true
            },handle:{[weak self] request,reply in
                guard let handler=self?.controlHandler else{reply(["error":"HOST_NOT_READY"]);return}
                handler(request,reply)
            })
            controlServer = try NyraControlServer(root:root,instance:instance,authenticate:{ [weak self] pid,uid,method in
                guard let self=self,self.accepts(pid:pid,uid:uid) else{return false}
                return ["focus","inspect"].contains(method) || self.canUserControl(pid)
            },handle:{ [weak self] request,reply in
                guard let handler=self?.controlHandler else{reply(["error":"HOST_NOT_READY"]);return}
                handler(request,reply)
            })
        } catch { endpointError = "LOCAL_STATUS_ENDPOINT_UNAVAILABLE" }
        observe(session: "unselected", task: nil, state: "idle", source: "twos_runtime")
    }
    deinit {
        focusServer?.stop()
        controlServer?.stop()
        socketSource?.cancel()
        if socketFD >= 0 { Darwin.close(socketFD) }
        if let root = socketDirectory {
            unlink(root.appendingPathComponent("status.sock").path); rmdir(root.path)
        }
    }
    func alias(_ opaqueSource: String) -> String {
        // Per-instance salt prevents exposing/recovering website paths from a
        // predictable path digest. The selected session remains stable in-process.
        SHA256.hash(data: Data((instance + "|" + opaqueSource).utf8)).map { String(format: "%02x", $0) }.joined()
    }
    static func validID(_ value: String) -> Bool {
        !value.isEmpty && value.utf8.count <= 128 && value.range(of: "^[A-Za-z0-9_-]+$", options: .regularExpression) != nil
    }
    func observe(session: String, task: String?, state: String, source: String, ownerEvidence: String? = nil, side: String? = nil, panes: [[String:Any]]? = nil, labels: [[String:String]]? = nil) {
        dispatchPrecondition(condition: .onQueue(.main))
        guard Self.validID(session), task.map(Self.validID) ?? true, Self.states.contains(state),
              ["twos_runtime", "codex_adapter", "web_handoff_adapter"].contains(source),
              side.map({["left","right","both"].contains($0)}) ?? true,
              state != "verified_success" || (source == "twos_runtime" && task != nil && ownerEvidence.map(Self.validID) == true) else { return }
        if let panes=panes {
            guard side != nil,panes.count==2,Set(panes.compactMap{$0["side"] as? String})==Set(["left","right"]),panes.allSatisfy({
                Set($0.keys)==Set(["side","state","reason","fresh"]) && Self.states.contains($0["state"] as? String ?? "") &&
                ($0["reason"] as? String)?.range(of:"^[A-Z0-9_]{1,80}$",options:.regularExpression) != nil && $0["fresh"] is Bool
            }) else{return}
        }
        if let labels=labels {
            guard let panes=panes,labels.count<=2,Set(labels.compactMap{$0["side"]}).count==labels.count,
                  labels.allSatisfy({ label in
                      Set(label.keys)==Set(["side","provider","title"]) &&
                      ["ChatGPT","Claude","DeepSeek","Codex"].contains(label["provider"] ?? "") &&
                      label["title"].map({!$0.isEmpty && $0.count<=90 && $0.rangeOfCharacter(from:.controlCharacters)==nil})==true &&
                      panes.contains(where:{$0["side"] as? String==label["side"] && $0["fresh"] as? Bool==true && ["running","queued","waiting_user"].contains($0["state"] as? String ?? "")})
                  }) else{return}
        }
        // Only the native result-confirmation path supplies an evidence ID.
        // Executor text and website replies have no acceptance authority.
        let key = session + "|" + (task ?? "")
        var effective = state, effectiveSource = source, effectiveEvidence = ownerEvidence
        if let terminal = terminalTasks[key], state != "verified_success" {
            // A delayed activity/terminal report cannot resurrect work or erase
            // an explicit result check. Keep the evidence and its source together.
            effective = terminal.state; effectiveSource = terminal.source; effectiveEvidence = terminal.evidence
        }
        if task != nil && ["completed_unverified", "partial", "failed", "cancelled", "verified_success"].contains(effective) {
            terminalTasks[key] = (effective, effectiveSource, effectiveEvidence)
        }
        // Bound memory; this is a live snapshot, never a history feed.
        if terminalTasks.count > 128 { terminalTasks = [key: (effective, effectiveSource, effectiveEvidence)] }
        if current["session_id"] as? String == session, current["task_id"] as? String == task,
           current["state"] as? String == effective, current["source"] as? String == effectiveSource,
           current["evidence_ref"] as? String == effectiveEvidence, current["activity_side"] as? String == side, (current["pane_observations"] as? [[String:Any]]).map({NSArray(array:$0).isEqual(to:panes ?? [])}) ?? (panes == nil), (current["task_labels"] as? [[String:String]]).map({NSArray(array:$0).isEqual(to:labels ?? [])}) ?? (labels == nil) { return }
        sequence += 1
        current = ["schema_version": labels != nil ? Self.schemaVersion : panes != nil ? "twos.nyra.status.v3" : (side == nil ? "twos.nyra.status.v1" : "twos.nyra.status.v2"), "producer_instance_id": instance,
                   "event_id": UUID().uuidString, "sequence": sequence,
                   "timestamp": ISO8601DateFormatter().string(from: Date()),
                   "session_id": session, "task_id": task as Any? ?? NSNull(),
                   "state": effective, "source": effectiveSource, "simulation": false]
        if effective == "verified_success", let evidence = effectiveEvidence { current["evidence_ref"] = evidence }
        if let side=side { current["activity_side"]=side }
        if let panes=panes { current["pane_observations"]=panes }
        if let labels=labels { current["task_labels"]=labels }
        let bytes = (try? JSONSerialization.data(withJSONObject: current, options: [.sortedKeys])) ?? Data()
        snapshotLock.lock(); wireSnapshot = bytes; snapshotLock.unlock()
    }
    func snapshot(_ reply: @escaping (Data) -> Void) {
        // Reads do not update sequence, start a model, replay an event or mutate
        // business state. A reconnect receives one snapshot, never celebration replay.
        DispatchQueue.main.async { reply((try? JSONSerialization.data(withJSONObject: self.current, options: [.sortedKeys])) ?? Data()) }
    }
    static func webState(_ value: String, observed: String? = nil, fresh: Bool = false) -> String {
        switch value {
        case "preparing", "queued", "busy": return "queued"
        // A durable send receipt proves delivery, not that the website is still
        // working. Only a fresh observation of this same transfer can drive work.
        // In particular, restart must not replay an old `sent` as live activity.
        case "sending", "sent": return fresh && ["sending", "sent"].contains(observed ?? "") ? "running" : "disconnected"
        case "reply": return "completed_unverified"
        case "cancelled", "generation_stopped": return "cancelled"
        case "login", "verification", "draft", "draft_conflict", "queue_paused", "target_changed": return "waiting_user"
        case "unsupported": return "failed"
        default: return "disconnected"
        }
    }
    static func codexState(run: CodexRunObservation, online: Bool, business: String?) -> String {
        if run.state == "failed" { return "failed" }
        if ["cancelled", "interrupted"].contains(run.state) { return "cancelled" }
        if run.state == "completed" {
            if business == "failed" { return "failed" }
            if ["partial", "blocked"].contains(business ?? "") { return "partial" }
            return "completed_unverified" // Includes executor-reported PASS.
        }
        if !online || run.serviceInterrupted == true || run.state == "unverified" { return "disconnected" }
        if !run.requests.isEmpty { return "waiting_user" }
        return "running"
    }
    func authorizeStandalone(_ app:NSRunningApplication) throws {
        guard NativeNyra.compatibleStandalone(app),let url=app.bundleURL,
              (Bundle(url:url)?.object(forInfoDictionaryKey:"NyraVisibilityProtocol") as? Int ?? 0)>=2,
              let hash=NativeNyra.signedCodeHash(url) else {throw CocoaError(.fileReadNoPermission)}
        let file=directory.appendingPathComponent("authorized-consumer.json")
        try JSONSerialization.data(withJSONObject:["path":url.path,"hash":hash.base64EncodedString(),"userControls":true]).write(to:file,options:.atomic)
        try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:file.path)
        snapshotLock.lock();authorizedStandalone=(url.path,hash);standaloneControls=true;snapshotLock.unlock()
    }
    func accepts(pid: pid_t, uid: uid_t) -> Bool {
        snapshotLock.lock();let approved=authorizedStandalone;snapshotLock.unlock()
        guard uid==getuid(),let app=NSRunningApplication(processIdentifier:pid),let path=app.bundleURL else{return false}
        let isEmbedded=app.bundleIdentifier=="com.tianma.workos.nyra" && path.standardizedFileURL==helper.standardizedFileURL
        let isStandalone=app.bundleIdentifier==NativeNyra.standaloneID && approved?.path==path.path
        guard isEmbedded || isStandalone else{return false}
        let selected=isEmbedded ? helper : path
        guard uid == getuid(),
              app.bundleURL?.standardizedFileURL == selected.standardizedFileURL,
              let executable = Bundle(url: selected)?.executableURL,
              app.executableURL?.standardizedFileURL == executable.standardizedFileURL,
              selected.resolvingSymlinksInPath() == selected.standardizedFileURL else { return false }
        let paths=[selected.path,executable.path,selected.appendingPathComponent("Contents/_CodeSignature/CodeResources").path]
        var stamp="\(pid)|\(app.launchDate?.timeIntervalSince1970 ?? 0)|\(selected.path)|\(approved?.hash.base64EncodedString() ?? "embedded")"
        for path in paths { var st=stat();guard lstat(path,&st)==0 else{return false};stamp += "|\(st.st_dev):\(st.st_ino):\(st.st_size):\(st.st_mtimespec.tv_sec):\(st.st_mtimespec.tv_nsec):\(st.st_ctimespec.tv_sec):\(st.st_ctimespec.tv_nsec)" }
        let now=ProcessInfo.processInfo.systemUptime
        snapshotLock.lock();let cached=verifiedPeers[pid];snapshotLock.unlock()
        if let cached=cached,cached.stamp==stamp,now-cached.at<30 {return true}
        if isStandalone {
            guard NativeNyra.compatibleStandalone(app),approved?.hash==NativeNyra.signedCodeHash(path) else{return false}
        }
        // Bind the live peer to the signed helper inside THIS app, not a name,
        // distributed notification or a mutable boolean supplied by a caller.
        var disk: SecStaticCode?; var live: SecCode?
        guard SecStaticCodeCreateWithPath(selected as CFURL, [], &disk) == errSecSuccess,
              SecStaticCodeCheckValidity(disk!, SecCSFlags(rawValue: kSecCSStrictValidate), nil) == errSecSuccess,
              SecCodeCopyGuestWithAttributes(nil, [kSecGuestAttributePid as String: pid] as CFDictionary, [], &live) == errSecSuccess,
              SecCodeCheckValidity(live!, [], nil) == errSecSuccess else { return false }
        var a: CFDictionary?; var b: CFDictionary?; var liveStatic: SecStaticCode?
        guard SecCodeCopyStaticCode(live!, [], &liveStatic) == errSecSuccess,
              SecCodeCopySigningInformation(disk!, [], &a) == errSecSuccess,
              SecCodeCopySigningInformation(liveStatic!, [], &b) == errSecSuccess,
              let expected = (a as? [String: Any])?[kSecCodeInfoUnique as String] as? Data,
              let actual = (b as? [String: Any])?[kSecCodeInfoUnique as String] as? Data else { return false }
        guard actual == expected else{return false}
        snapshotLock.lock();if verifiedPeers.count>16 {verifiedPeers.removeAll()}
        verifiedPeers[pid]=(stamp,now);snapshotLock.unlock();return true
    }
    func canUserControl(_ pid:pid_t)->Bool {
        guard let app=NSRunningApplication(processIdentifier:pid),let path=app.bundleURL else{return false}
        if app.bundleIdentifier=="com.tianma.workos.nyra",path.standardizedFileURL==helper.standardizedFileURL{return true}
        snapshotLock.lock();defer{snapshotLock.unlock()}
        return standaloneControls && authorizedStandalone?.path==path.path
    }
    private func acceptSnapshots() {
        dispatchPrecondition(condition: .onQueue(socketQueue))
        // Full code/resource validation can fault pages or await the OS. It
        // stays serial and off the UI; only immutable payload copying is locked.
        // Bounded nonblocking writes; a stalled/malicious subscriber cannot hold
        // the UI or execution thread. No request bytes or commands are accepted.
        for _ in 0..<8 {
            let peer = Darwin.accept(socketFD, nil, nil)
            guard peer >= 0 else { return }
            defer { Darwin.close(peer) }
            var uid: uid_t = 0; var gid: gid_t = 0; var pid: pid_t = 0
            var size = socklen_t(MemoryLayout<pid_t>.size)
            guard getpeereid(peer, &uid, &gid) == 0,
                  getsockopt(peer, SOL_LOCAL, LOCAL_PEERPID, &pid, &size) == 0,
                  accepts(pid: pid, uid: uid) else { continue }
            // A consumer can time out/close while peer identity is checked.
            // A failed socket option must never fall through to send(): on
            // Darwin an unprotected broken pipe terminates the whole host.
            var noSignal: Int32 = 1
            guard setsockopt(peer, SOL_SOCKET, SO_NOSIGPIPE, &noSignal, socklen_t(MemoryLayout<Int32>.size)) == 0 else { continue }
            snapshotLock.lock(); let data = wireSnapshot; snapshotLock.unlock()
            guard !data.isEmpty else { continue }
            let line = data + Data([10])
            _ = line.withUnsafeBytes { Darwin.send(peer, $0.baseAddress, $0.count, MSG_DONTWAIT | MSG_NOSIGNAL) }
        }
    }
}

// Validate before dismissing the sheet. A rejected address remains editable;
// no route, draft, automatic exchange or browser is changed by Cancel.
final class WebsiteAddressPrompt: NSObject {
    let alert = NSAlert()
    let field = NSTextField(frame: NSRect(x: 0, y: 52, width: 440, height: 28))
    let errorLabel = NSTextField(wrappingLabelWithString: "")
    let translate: (String) -> String
    private var acceptedURL: URL?
    private var finished = false
    init(translate: @escaping (String) -> String) { self.translate = translate; super.init() }
    func show(on window: NSWindow, current: String, completion: @escaping (URL?) -> Void) {
        alert.messageText = translate("Open a website in this pane")
        alert.informativeText = translate("Enter an HTTPS address, or an HTTP address on this Mac or your private network. HTTP is not encrypted. Nothing is sent to the other pane automatically.")
        let content = NSView(frame: NSRect(x: 0, y: 0, width: 440, height: 84))
        field.placeholderString = "https://… / http://192.168.…"; field.stringValue = current
        field.setAccessibilityLabel(translate("Website address"))
        errorLabel.frame = NSRect(x: 0, y: 0, width: 440, height: 44)
        errorLabel.textColor = .systemRed; errorLabel.font = .systemFont(ofSize: 12)
        errorLabel.isHidden = true; content.addSubview(field); content.addSubview(errorLabel)
        alert.accessoryView = content
        let open = alert.addButton(withTitle: translate("Open")); open.target = self; open.action = #selector(accept)
        alert.addButton(withTitle: translate("Cancel"))
        alert.window.initialFirstResponder = field
        alert.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { return }
            self.finished = true
            completion(response == .alertFirstButtonReturn ? self.acceptedURL : nil)
        }
    }
    @objc func accept() {
        guard !finished, let parent = alert.window.sheetParent else { return }
        let input = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = IntegratedWorkbench.validWebsite(input) else {
            errorLabel.stringValue = translate(IntegratedWorkbench.websiteInputError(input))
            errorLabel.isHidden = false; alert.window.makeFirstResponder(field)
            return
        }
        finished = true; acceptedURL = url
        parent.endSheet(alert.window, returnCode: .alertFirstButtonReturn)
    }
}

// A single app/window owns both panes. No foreign window positioning, capture,
// screen mirror, remote-control service, or keyboard synthesis is involved.
final class IntegratedWorkbench: NSWindowController, NSWindowDelegate, NSTextViewDelegate {
    let preferences: URL
    let resources: URL?
    let translate: (String) -> String
    let openProjects: () -> Void
    var languageChanged: ((String) -> Bool)?
    var toolbarTitle: NSTextField?
    let languagePicker = NSPopUpButton(frame: .zero, pullsDown: false)
    let split = NSSplitView()
    let leftPicker = NSPopUpButton(frame: .zero, pullsDown: false)
    let rightPicker = NSPopUpButton(frame: .zero, pullsDown: false)
    var webPanes: [Int: NativeWorkbench] = [:]
    var webCache: [String: NativeWorkbench] = [:]
    var codex: NativeCodex?
    var websitePrompt: WebsiteAddressPrompt?
    var kinds = ["ChatGPT", "Codex"]
    var urls = [NativeWorkbench.home.absoluteString, ""]
    let options = ["ChatGPT", "Codex", "Claude", "DeepSeek", "Website…"]
    let defaults = ["ChatGPT": "https://chatgpt.com/", "Claude": "https://claude.ai/", "DeepSeek": "https://chat.deepseek.com/"]
    var lastResultOrigin: URL?
    var routeRevision = UUID().uuidString
    var routeSignatures: [Int: String] = [:]
    var webTransfers: [WebHandoffReceipt] = []
    var transferTimers: [String: Timer] = [:]
    var webLedgerError = false
    var activeWebQueues = Set<String>()
    var webRuntimeObservations: [String: (state: String, uptime: TimeInterval)] = [:]
    var inspectionsInFlight = Set<String>()
    var paneActivities: [Int:PaneActivity] = [:]
    var paneObservationPending = Set<Int>()
    var paneActivityRunIDs: [Int:String] = [:]
    var paneActivityTokens: [Int:String] = [:]
    var nyraTaskRows: [Int:[String:Any]] = [:]
    var nyraStops: [Int:(task:String?,at:Double)] = [:]
    var dialogue: PairedDialogue?
    var dialogueTickInFlight = false
    var dialogueNavigationReads: [String:Int] = [:]
    var dialogueWindow: NSWindow?
    var dialogueStatus: NSTextField?
    var dialogueText: NSTextView?
    var dialogueRoles: [NSTextField] = []
    var dialogueRounds: NSTextField?
    var dialogueMinutes: NSTextField?
    var dialogueConcession: NSButton?
    var dialogueUntilStopped: NSButton?
    var dialogueSeed: (source:String, message:String, hash:String)?
    var dialogueStartPending = false
    var dialogueStartToken: String?
    var webFileSelections: [Int:[WebTransferFile]] = [:]
    let dialogueButton = NSButton(title:"",target:nil,action:nil)
    var nyraObservationTimer: Timer?
    var handoffWindow: NSWindow?
    let handoffPicker = NSPopUpButton(frame: .zero, pullsDown: false)
    let handoffDetail = NSTextView()
    let handoffHistoryButton = NSButton(title: "", target: nil, action: nil)
    var historyButtons: [(NSButton, String)] = []
    var historyReopenButton: NSButton?
    let nyraButton = NSButton(title: "Nyra", target: nil, action: nil)
    var nyraStatusWindow: NSWindow?
    var nyraStatusText: NSTextField?
    let nyraAuthorizeControlsButton=NSButton(title:"",target:nil,action:nil)
    let nyraConnectionButton = NSButton(title:"Nyra status",target:nil,action:nil)
    lazy var nyraStatus = NyraStatusProducer(directory: preferences.appendingPathComponent("nyra-status"), helper: Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/TWOS Nyra.app"))
    lazy var nyra = NativeNyra(stateRoot: preferences.appendingPathComponent("nyra"), producerInstance: { [weak self] in self?.nyraStatus.instance }, authorizeConsumer:{ [producer=nyraStatus] app in
        try producer.authorizeStandalone(app)
    }) { [weak self] state in
        guard let self = self else { return }
        let visible = state["visible"] as? Bool == true
        self.nyraButton.title = self.translate(state["available"] as? Bool == false ? "Nyra · view status" : (visible ? "Hide Nyra" : "Show Nyra"))
        self.nyraButton.isEnabled = state["pending"] as? Bool != true
        self.nyraButton.toolTip = state["reason"] as? String
        self.nyraButton.setAccessibilityLabel(self.nyraButton.title)
        self.codex?.emit("nyra", state)
        self.updateNyraStatusView(state)
    }

    init(preferences: URL, resources: URL? = nil, translate: @escaping (String) -> String, openProjects: @escaping () -> Void) {
        self.resources = resources ?? Bundle.main.resourceURL?.appendingPathComponent("engine/_internal/static_cockpit")
        self.preferences = preferences; self.translate = translate; self.openProjects = openProjects
        let ledgerFile = preferences.appendingPathComponent("web-handoff-receipts.json")
        if FileManager.default.fileExists(atPath: ledgerFile.path) {
            do { webTransfers = try JSONDecoder().decode([WebHandoffReceipt].self, from: Data(contentsOf: ledgerFile)) }
            catch { webLedgerError = true }
        }
        // A crash during submit is not permission to retry it.
        for i in webTransfers.indices where webTransfers[i].state == "sending" { webTransfers[i].state = "unknown" }
        for i in webTransfers.indices where webTransfers[i].state == "queued" { webTransfers[i].state = "queue_paused" }
        if let data = try? Data(contentsOf: preferences.appendingPathComponent("paired-workbench.json")),
           let saved = try? JSONSerialization.jsonObject(with: data) as? [String: String] {
            for n in 0...1 {
                if let kind = saved["kind\(n)"], options.contains(kind) { kinds[n] = kind }
                if let raw = saved["url\(n)"], Self.validWebsite(raw) != nil { urls[n] = raw }
            }
            if kinds == ["Codex", "Codex"] { kinds[0] = "ChatGPT"; urls[0] = NativeWorkbench.home.absoluteString }
        }
        let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1440, height: 860), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        win.title = "TWOS"; win.minSize = NSSize(width: 1080, height: 600); win.isReleasedWhenClosed = false
        super.init(window: win)
        if let bytes=try? Data(contentsOf:preferences.appendingPathComponent("web-transfer-selections.json")) {
            webFileSelections=(try? JSONDecoder().decode([Int:[WebTransferFile]].self,from:bytes)) ?? [:]
        }
        if let bytes=try? Data(contentsOf:preferences.appendingPathComponent("paired-dialogue.json")) {
            do {
                dialogue=try JSONDecoder().decode(PairedDialogue.self,from:bytes)
                guard dialogue?.valid==true else {throw CocoaError(.fileReadCorruptFile)}
                if dialogue?.state == "running" { dialogue?.state="paused";dialogue?.reason="App restarted. Auto-send is off. Check the receipt before explicitly continuing." }
                // Receipts survive restart; permission to resume does not.
                dialogue?.autoSendEnabled=false
            } catch { dialogue=nil;webLedgerError=true }
        }
        for (n, picker) in [leftPicker, rightPicker].enumerated() {
            picker.addItems(withTitles: options.map { translate($0) }); picker.selectItem(at: options.firstIndex(of: kinds[n]) ?? 0)
            picker.tag = n; picker.target = self; picker.action = #selector(changePane(_:))
            picker.setAccessibilityLabel(translate(n == 0 ? "Left service" : "Right service"))
        }
        let title = NSTextField(labelWithString: translate("One workspace · two connected contexts"))
        title.textColor = .secondaryLabelColor; toolbarTitle = title
        title.lineBreakMode = .byTruncatingTail
        title.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        languagePicker.addItems(withTitles: ["Language: English", "语言：简体中文"])
        languagePicker.selectItem(at: translate("Back") == "Back" ? 0 : 1)
        languagePicker.target = self; languagePicker.action = #selector(changeLanguage(_:))
        languagePicker.setAccessibilityLabel("Language / 语言")
        let spacer = NSView(); spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        nyraButton.target = self; nyraButton.action = #selector(toggleNyra)
        nyraConnectionButton.target=self;nyraConnectionButton.action=#selector(connectNyra);nyraConnectionButton.title=translate("Nyra status")
        handoffHistoryButton.title = translate("Handoff history")
        handoffHistoryButton.target = self; handoffHistoryButton.action = #selector(showWebHistory)
        dialogueButton.title=translate("Automatic exchange");dialogueButton.target=self;dialogueButton.action=#selector(showDialogue)
        let bar = NSStackView(views: [leftPicker, title, spacer, languagePicker, nyraButton, rightPicker]); bar.spacing = 10
        bar.edgeInsets = NSEdgeInsets(top: 10, left: 14, bottom: 10, right: 14)
        bar.translatesAutoresizingMaskIntoConstraints = false
        split.isVertical = true; split.dividerStyle = .thin; split.translatesAutoresizingMaskIntoConstraints = false
        win.contentView!.addSubview(bar); win.contentView!.addSubview(split)
        NSLayoutConstraint.activate([
            bar.leadingAnchor.constraint(equalTo: win.contentView!.leadingAnchor), bar.topAnchor.constraint(equalTo: win.contentView!.topAnchor),
            bar.trailingAnchor.constraint(equalTo: win.contentView!.trailingAnchor),
            split.topAnchor.constraint(equalTo: bar.bottomAnchor), split.leadingAnchor.constraint(equalTo: win.contentView!.leadingAnchor),
            split.trailingAnchor.constraint(equalTo: win.contentView!.trailingAnchor), split.bottomAnchor.constraint(equalTo: win.contentView!.bottomAnchor)])
        for _ in 0...1 { split.addArrangedSubview(NSView()) }
        nyraStatus.controlHandler = { [weak self] request,reply in
            guard let self=self else{reply(["error":"HOST_CLOSED"]);return}
            self.handleNyraControl(request,reply:reply)
        }
        rebuild(0); rebuild(1); refreshTargets(); nyra.refresh(); win.center()
        let statusTimer = Timer(timeInterval: 2, repeats: true) { [weak self] _ in self?.refreshNyraStatus();self?.nyra.refresh();self?.tickDialogue();self?.refreshAutomaticReplyState() }
        nyraObservationTimer = statusTimer; RunLoop.main.add(statusTimer, forMode: .common)
    }
    deinit { nyraObservationTimer?.invalidate() }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    static func validWebsite(_ raw: String) -> URL? {
        guard let url = URL(string: raw), let host = url.host, !host.isEmpty, url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil else { return nil }
        if url.scheme == "https" { return url }
        if url.scheme == "http" && NativeWorkbench.isLocalDashboardHost(host) { return url }
        return nil
    }
    static func websiteInputError(_ raw: String) -> String {
        guard !raw.isEmpty, let url = URL(string: raw), let host = url.host, !host.isEmpty else {
            return "Enter a complete address starting with https:// or http://."
        }
        if url.user != nil || url.password != nil { return "Addresses containing a username or password cannot be opened here." }
        if url.query != nil || url.fragment != nil { return "Open a page without query parameters or a fragment, then navigate within the site." }
        if url.scheme == "http" { return "HTTP is supported only for localhost or a private IPv4 address (10.x, 172.16–31.x or 192.168.x). Use HTTPS for other sites." }
        return "Only HTTPS websites and local HTTP dashboards can be opened here."
    }
    @objc func toggleNyra() {
        _ = nyraStatus
        if nyra.snapshot()["available"] as? Bool == false { connectNyra(); return }
        nyra.toggle()
    }
    @objc func changeLanguage(_ sender: NSPopUpButton) {
        let locale = sender.indexOfSelectedItem == 1 ? "zh-CN" : "en-US"
        guard languageChanged?(locale) == true else {
            sender.selectItem(at: translate("Back") == "Back" ? 0 : 1)
            let alert = NSAlert()
            alert.messageText = translate("Language preference could not be saved. Existing data is unchanged.")
            if let window = window { alert.beginSheetModal(for: window) }
            return
        }
        refreshLanguage()
    }
    @objc func connectNyra() {
        _ = nyraStatus
        if let app=nyra.standalone,nyra.snapshot()["binding"] as? String != "CONNECTED_READONLY" {nyra.connectStandalone(app)}
        if nyraStatusWindow == nil {
            let w=NSWindow(contentRect:NSRect(x:0,y:0,width:680,height:540),styleMask:[.titled,.closable,.resizable],backing:.buffered,defer:false)
            w.isReleasedWhenClosed=false;w.delegate=self
            let text=NSTextField(wrappingLabelWithString:"");text.isSelectable=true;text.font = .monospacedSystemFont(ofSize:13,weight:.regular);text.translatesAutoresizingMaskIntoConstraints=false
            w.contentView!.addSubview(text)
            nyraAuthorizeControlsButton.target=self;nyraAuthorizeControlsButton.action=#selector(authorizeNyraUserControls)
            nyraAuthorizeControlsButton.translatesAutoresizingMaskIntoConstraints=false;w.contentView!.addSubview(nyraAuthorizeControlsButton)
            NSLayoutConstraint.activate([text.leadingAnchor.constraint(equalTo:w.contentView!.leadingAnchor,constant:20),text.trailingAnchor.constraint(equalTo:w.contentView!.trailingAnchor,constant:-20),text.topAnchor.constraint(equalTo:w.contentView!.topAnchor,constant:20)])
            NSLayoutConstraint.activate([nyraAuthorizeControlsButton.trailingAnchor.constraint(equalTo:w.contentView!.trailingAnchor,constant:-20),nyraAuthorizeControlsButton.bottomAnchor.constraint(equalTo:w.contentView!.bottomAnchor,constant:-16)])
            nyraStatusWindow=w;nyraStatusText=text
        }
        updateNyraStatusView(nyra.snapshot());nyra.refresh()
        nyraStatusWindow?.center();nyraStatusWindow?.makeKeyAndOrderFront(nil)
    }
    @objc func authorizeNyraUserControls(){
        guard let app=nyra.standalone else{return}
        nyra.connectStandalone(app)
    }
    func updateNyraStatusView(_ state:[String:Any]) {
        guard let text=nyraStatusText else{return}
        nyraStatusWindow?.title=translate("Nyra status")
        let unknown=translate("Unknown")
        func value(_ key:String)->String {
            if ["heartbeatAge","snapshotAge"].contains(key),let seconds=state[key] as? Double,seconds.isFinite {return String(format:"%.1f",max(0,seconds))}
            if key=="frameTimer",let active=state[key] as? Bool {return translate(active ? "Running" : "Stopped")}
            return state[key].map{String(describing:$0)} ?? unknown
        }
        var lines=[translate("Transport")+": "+value("binding"),translate("Visible consumer")+": PID "+value("consumerPID")+" · "+value("consumerInstance"),translate("Heartbeat age")+": "+value("heartbeatAge")+" s",translate("Last snapshot age")+": "+value("snapshotAge")+" s",translate("Last state change")+": "+value("lastStateChangeAt")]
        for side in ["left","right"] {
            let item=(state["paneObservations"] as? [[String:Any]])?.first{$0["side"] as? String==side}
            lines.append(translate(side=="left" ? "Left activity" : "Right activity")+": "+(item?["state"] as? String ?? unknown)+" · "+(item?["reason"] as? String ?? "NO_OBSERVATION")+" · "+translate(item?["fresh"] as? Bool == true ? "Fresh" : "Stale"))
        }
        lines.append(translate("Actual animation")+": "+value("animation")+" / "+value("frameAsset"))
        lines.append(translate("Frames displayed")+": "+value("frameCount")+" · "+translate("Animation timer")+": "+value("frameTimer"))
        if state["reduceMotion"] as? Bool == true {lines.append(translate("Reduced motion is enabled. Animation is intentionally still."))}
        if let reason=state["reason"] as? String {lines.append(translate(reason))}
        if let code=state["interactionError"] as? String {lines.append(translate("Nyra status")+": "+code)}
        let zh=translate("Back") != "Back"
        lines.append(zh ? "状态、活动和动画分别核验。状态通道不共享聊天正文；主动追加／编辑通过单独已认证控制通道传递所选输入。":"Connection, activity and animation are checked separately. Status excludes chat bodies; explicit append/edit actions carry the selected input over a separate authenticated control channel.")
        let standalone=nyra.standalone
        nyraAuthorizeControlsButton.title=zh ? "启用夜璃任务控制…":"Enable Nyra task controls…"
        nyraAuthorizeControlsButton.isHidden=standalone.map{nyraStatus.canUserControl($0.processIdentifier)} ?? true
        nyraAuthorizeControlsButton.isEnabled=state["pending"] as? Bool != true
        text.stringValue=lines.joined(separator:"\n\n")
    }
    func refreshLanguage() {
        languagePicker.selectItem(at: translate("Back") == "Back" ? 0 : 1)
        nyra.refresh()
        nyraConnectionButton.title=translate("Nyra status")
        refreshDialogueUI()
        handoffHistoryButton.title = translate("Handoff history")
        handoffWindow?.title = translate("Handoff history")
        historyButtons.forEach { $0.0.title = translate($0.1) }
        refreshWebHistory()
        toolbarTitle?.stringValue = translate("One workspace · two connected contexts")
        for picker in [leftPicker, rightPicker] {
            for (index, option) in options.enumerated() { picker.item(at: index)?.title = translate(option) }
            picker.setAccessibilityLabel(translate(picker.tag == 0 ? "Left service" : "Right service"))
        }
        webCache.values.forEach { $0.refreshLanguage() };for index in 0...1 {updateWebFileLabel(index)}; refreshTargets()
    }
    func start() {
        showWindow(nil); NSApp.activate(ignoringOtherApps: true)
        split.adjustSubviews()
        if split.bounds.width > 0 { split.setPosition(split.bounds.width * 0.52, ofDividerAt: 0) }
    }
    func windowWillClose(_ notification: Notification) {
        guard let closing = notification.object as? NSWindow,
              closing === handoffWindow || closing === dialogueWindow || closing === nyraStatusWindow else { return }
        // Closing an auxiliary view returns to this workbench, not another
        // installed TWOS instance. It never navigates, resumes, or dispatches.
        DispatchQueue.main.async { [weak self] in
            guard let main = self?.window, main.isVisible, NSApp.isActive else { return }
            main.makeKeyAndOrderFront(nil)
        }
    }
    @objc func changePane(_ sender: NSPopUpButton) {
        let index = sender.tag, next = options[sender.indexOfSelectedItem], previous = kinds[index]
        if previous == "Codex", codex?.isBusy == true { sender.selectItem(at: options.firstIndex(of: previous)!); return }
        if next == "Website…" {
            sender.selectItem(at: options.firstIndex(of: previous) ?? 0)
            guard websitePrompt == nil, let window = window, window.attachedSheet == nil else { return }
            let prompt = WebsiteAddressPrompt(translate: translate); websitePrompt = prompt
            prompt.show(on: window, current: previous == "Website…" ? urls[index] : "") { [weak self] url in
                guard let self = self else { return }
                self.websitePrompt = nil
                guard let url = url, self.kinds[index] == previous,
                      previous != "Codex" || self.codex?.isBusy != true else { return }
                self.applyPaneSelection(index, next: next, website: url)
            }
            return
        }
        applyPaneSelection(index, next: next)
    }
    func applyPaneSelection(_ index: Int, next: String, website: URL? = nil) {
        let previous = kinds[index]
        pauseDialogue("Participant selection changed")
        if next == "Codex", kinds[1-index] == "Codex" {
            // Move the same live pane; never create another Codex connection.
            kinds[1-index] = previous; urls[1-index] = urls[index]
            if let pane = webPanes[index] {
                webPanes[1-index] = pane
                webPanes.removeValue(forKey: index)
                webCache.removeValue(forKey: "\(index):\(pane.serviceHome.absoluteString)")
                webCache["\(1-index):\(pane.serviceHome.absoluteString)"] = pane
                pane.locationKey = "paired-location-\(1-index)-\(pane.serviceHome.host ?? "web").json"
                pane.updateNavigation()
                configureHandoff(pane, index: 1-index)
                pane.handoffHandler = { [weak self] text, source in self?.handoff(text, source: source, from: 1-index) }
            }
            (index == 0 ? rightPicker : leftPicker).selectItem(at: options.firstIndex(of: previous) ?? 0)
        }
        if let website = website { urls[index] = website.absoluteString }
        else if let url = defaults[next] { urls[index] = url }
        for pane in webCache.values {
            pane.web.evaluateJavaScript("window.twosTransferLease = Math.random().toString()", in: nil, in: NativeWorkbench.handoffWorld, completionHandler: nil)
        }
        for i in webTransfers.indices where webTransfers[i].state == "queued" {
            activeWebQueues.remove(webTransfers[i].id); transferTimers[webTransfers[i].id]?.invalidate(); webTransfers[i].state = "queue_paused"
        }
        _ = persistWebTransfers()
        kinds[index] = next
        (index == 0 ? leftPicker : rightPicker).selectItem(at: options.firstIndex(of: next) ?? 0)
        routeRevision = UUID().uuidString
        rebuild(0, navigateTo: index == 0 ? website : nil); rebuild(1, navigateTo: index == 1 ? website : nil); refreshTargets(); save()
    }
    func save() {
        try? NativeWorkbench.save(["kind0": kinds[0], "kind1": kinds[1], "url0": urls[0], "url1": urls[1]], at: preferences.appendingPathComponent("paired-workbench.json"))
    }
    func rebuild(_ index: Int, navigateTo: URL? = nil) {
        let host = split.arrangedSubviews[index]
        host.subviews.forEach { $0.removeFromSuperview() }
        let view: NSView
        if kinds[index] == "Codex" {
            if codex == nil, let resource = resources {
                codex = NativeCodex(resources: resource, preferences: preferences, translate: translate)
                codex?.statusMetadataChanged = { [weak self] in self?.refreshNyraStatus() }
                codex?.nyraAction = { [weak self] action in if action == "toggle" { self?.nyra.toggle() } else { self?.nyra.refresh() } }
                codex?.languageChanged = { [weak self] locale in
                    guard let self = self, self.languageChanged?(locale) == true else { return false }
                    self.refreshLanguage(); return true
                }
                codex?.returnResult = { [weak self] text, source in self?.bringBack(text, source: source) }
                codex?.handoffChanged = { [weak self] record in
                    self?.webCache.values.forEach { $0.showHandoffProgress(record.card) }
                    if record.returnState == nil { self?.returnDelivery(record.id, explicit: false) }
                }
            }
            view = codex?.web ?? NSTextField(labelWithString: translate("The bundled Codex pane is unavailable."))
        } else {
            let home = Self.validWebsite(urls[index]) ?? NativeWorkbench.home
            if webPanes[index]?.serviceHome != home {
                let cacheKey = "\(index):\(home.absoluteString)"
                let pane = webCache[cacheKey] ?? NativeWorkbench(preferences: preferences, translate: translate, openProjects: openProjects,
                                           serviceHome: home, locationKey: "paired-location-\(index)-\(home.host ?? "web").json", handoffResources: resources)
                pane.handoffHandler = { [weak self] text, source in self?.handoff(text, source: source, from: index) }
                configureHandoff(pane, index: index)
                webPanes[index] = pane; webCache[cacheKey] = pane
            }
            let pane = webPanes[index]!
            view = pane.paneView // Keep native navigation and transfer controls with the page.
            pane.window?.contentView = nil
            pane.start(embedded: true, navigateTo: navigateTo)
            updateWebFileLabel(index)
        }
        view.translatesAutoresizingMaskIntoConstraints = false; host.addSubview(view)
        NSLayoutConstraint.activate([view.leadingAnchor.constraint(equalTo: host.leadingAnchor), view.trailingAnchor.constraint(equalTo: host.trailingAnchor),
                                     view.topAnchor.constraint(equalTo: host.topAnchor), view.bottomAnchor.constraint(equalTo: host.bottomAnchor)])
    }
    func configureHandoff(_ pane: NativeWorkbench, index: Int) {
        pane.automaticReplyHandler = { [weak self] enabled,source in self?.setAutomaticReplies(enabled,from:index,source:source) }
        pane.historyHandler = { [weak self] in self?.showWebHistory() }
        pane.diagnosticsHandler = { [weak self] in self?.connectNyra() }
        pane.chooseFiles = { [weak self] in self?.chooseWebFiles(index) }
        pane.clearFiles = { [weak self] in self?.clearWebFiles(index) }
        pane.inspectHandler = { [weak self, weak pane] id, source in
            guard let self = self else { return }
            guard let record = self.webTransfers.first(where: { $0.id == id && $0.source == source.absoluteString }) else { pane?.showNotice("This handoff receipt is unavailable. Nothing was sent."); return }
            guard self.kinds[record.targetPane] == record.provider, let target = self.webPanes[record.targetPane] else {
                pane?.showNotice("Open the original destination pane to check this handoff. Nothing will be resent."); return
            }
            self.inspectWebTransfer(id, target: target)
        }
        pane.instructionHandler = { [weak self] text, source, message in
            guard let self = self else { return }
            self.handoff(text, source: source, from: index, message: message)
        }
        pane.retryHandler = { [weak self, weak pane] id, source in
            guard let self = self else { return }
            if let record = self.webTransfers.first(where: { $0.id == id && $0.source == source.absoluteString }) {
                guard self.currentTargetMatches(record) else { pane?.showNotice("The destination changed. Review the current destination and send again."); return }
                if record.mayHaveSent == true || ["sending", "unknown", "sent", "reply"].contains(record.state), let target = self.webPanes[record.targetPane] {
                    self.inspectWebTransfer(record.id, target: target); return
                }
                self.handoff(record.text, source: source, from: index, message: record.message)
            } else if self.kinds[1-index] == "Codex" { self.codex?.retryHandoff(id, source: source) }
        }
        pane.navigationChanged = { [weak self] in self?.refreshTargets() }
        pane.navigationReady = { [weak self, weak pane] in
            guard let self = self, let pane = pane, self.webPanes[index] === pane else { return }
            // Re-enable only the actions now proven valid for the restored
            // destination. Navigation never inspects or dispatches a message.
            self.refreshWebHistory()
            guard self.kinds[index] == "Claude" else { return }
            guard let url = NativeWorkbench.restorableURL(pane.web.url, service: pane.serviceHome) else {
                if let actual = pane.web.url, actual.scheme == "https", actual.host == "claude.ai", actual.path == "/login" {
                    pane.showNotice("Claude sign-in is available. Sign in on this page; no task has been sent.")
                }
                return
            }
            // One read-only phase check after navigation. Never operate challenge
            // controls, reload repeatedly, change UA/storage, or resume a draft.
            pane.webTransfer(["provider":"Claude","targetURL":url.absoluteString,"readinessOnly":true,"inspectOnly":true]) { [weak pane] value in
                guard let pane = pane, NativeWorkbench.restorableURL(pane.web.url, service:pane.serviceHome) == url else { return }
                if value["state"] as? String == "verification" { pane.showNotice("Claude is waiting for website verification. No task was sent. Open in Safari is a fallback, not embedded verification success.") }
                else if value["state"] as? String == "input_ready" { pane.showNotice("Claude input is ready. Handoff sends only the instruction you select.") }
            }
        }
        pane.handoffReady = { [weak self, weak pane] in
            self?.refreshTargets()
            self?.refreshAutomaticReplyState()
            self?.webTransfers.forEach { pane?.showHandoffProgress($0.card) }
            for item in self?.codex?.ledger.submissions ?? [] {
                pane?.showHandoffProgress(item.card)
                if item.returnState == nil || ["pending", "unknown"].contains(item.returnState ?? "") { self?.returnDelivery(item.id, explicit: false) }
            }
        }
        pane.discussResult = { [weak self] id in
            self?.returnDelivery(id, explicit: true)
        }
        pane.sendWebReply = { [weak self] id, _ in self?.sendRecordedWebReply(id) }
        pane.stopExchangeHandler = { [weak self] in
            self?.stopDialogue()
            self?.webPanes.values.forEach { $0.showNotice("Automatic exchange stopped. In-flight replies may finish; no next message will be sent.") }
        }
        pane.nativeStopHandler = { [weak self, weak pane] source in
            guard let self=self, let pane=pane, self.webPanes[index] === pane else{return}
            self.stopDialogueFromPane(index,source:source)
        }
    }
    func returnDelivery(_ id: String, explicit: Bool) {
        guard let client = codex, let record = client.ledger.submissions.first(where: { $0.id == id }),
              ["completed", "failed", "interrupted"].contains(record.state), record.returnState != "confirmed", record.returnState != "sending",
              let source = record.source.flatMap(URL.init(string:)),
              let pane = webPanes.values.first(where: { NativeWorkbench.restorableURL($0.web.url, service: $0.serviceHome) == source }) else { return }
        if !explicit && record.returnState != nil && !["pending", "unknown"].contains(record.returnState ?? "") { return }
        let inspectOnly = record.returnState == "unknown"
        let summary = "Codex execution result / Codex 执行回传\n" + "Channel / 执行通道: " + record.state + "\nBusiness report / 业务回报: " + record.businessResult + "\nFolder / 目录: " + record.directory.path + "\n\n" + (record.result ?? "") + (record.error.map { "\nError / 错误: " + $0 } ?? "") + "\n\ncompleted 只代表通道结束；reported_pass 只是执行器回报，尚非独立产物验收。请结合以上真实执行结果继续讨论；不要把未完成或失败记录描述为成功，也不要自行发起新执行。"
        // Save return intent before invoking the website's real Send. An
        // ambiguous website receipt is inspected, never blindly resubmitted.
        guard let index = client.ledger.submissions.firstIndex(where: { $0.id == id }) else { return }
        client.ledger.submissions[index].returnState = "sending"
        guard client.persistLedger() else { return }
        pane.deliverResult(summary, id: id, source: source, inspectOnly: inspectOnly) { [weak self] state in
            self?.codex?.changeSubmission(id) { $0.returnState = state }
            if state == "confirmed" {
                self?.codex?.notice("The result has returned to the original discussion.")
            } else {
                self?.codex?.notice(state == "unknown" ? "The result is saved beside the original instruction; website delivery needs verification and will not be repeated." : "The result is saved beside the original instruction. It will return when this discussion finishes and its composer is empty; your draft is preserved.")
            }
        }
    }
    func routeSignature(_ index: Int) -> String {
        let destination = 1-index
        let location = kinds[destination] == "Codex" ? (codex?.threadID ?? "unselected") : (webPanes[destination]?.web.url.flatMap { NativeWorkbench.restorableURL($0, service: webPanes[destination]!.serviceHome) }?.absoluteString ?? "unloaded")
        return [routeRevision, String(destination), kinds[destination], location].joined(separator: "|")
    }
    func refreshTargets() {
        for (index, pane) in webPanes where kinds[index] != "Codex" {
            let signature = routeSignature(index)
            routeSignatures[index] = signature
            pane.updateTarget(provider: kinds[1-index], binding: signature)
        }
        refreshNyraStatus()
    }
    func refreshNyraStatus() {
        // Each selected pane is independently observed. No conversation body,
        // filename, account or credential enters the companion protocol.
        // Owner-enabled task labels separately use bounded visible conversation titles.
        let now=ProcessInfo.processInfo.systemUptime
        for index in 0...1 {
            if kinds[index] == "Codex", let client=codex, let thread=client.threadID {
                let run=client.telemetry.runs.values.filter {
                    $0.thread==thread && (client.canControl || client.tailTurn==nil || $0.turn==client.tailTurn)
                }.max { $0.lastActivity<$1.lastActivity }
                var state=client.connected && !client.uncertain && client.canControl ? "idle" : "activity_unknown"
                var evidence:String?
                if let run=run { state=NyraStatusProducer.codexState(run:run,online:client.connected && !client.uncertain,business:client.observedSubmission(for:run)?.businessResult) }
                if let run=run,run.state=="completed",client.connected && !client.uncertain,
                   let check=client.observedSubmission(for:run)?.validOwnerResultCheck {
                    state="verified_success";evidence=nyraStatus.alias(check.id)
                }
                if run?.terminal != false, client.ledger.submissions.contains(where:{$0.thread==thread && $0.turn==nil && ["queued","preparing","sending","accepted"].contains($0.state)}) { state="queued" }
                paneActivities[index]=PaneActivity(session:nyraStatus.alias(thread),task:run?.turn,state:state == "disconnected" ? "activity_unknown" : state,at:now,evidence:evidence,reason:!client.connected || client.uncertain ? "CODEX_CONNECTION_UNAVAILABLE" : run != nil || client.canControl ? "CODEX_STATE_OBSERVED" : "EXTERNAL_RUN_STATE_NOT_EXPOSED")
            } else if let pane=webPanes[index], kinds[index] != "Codex", let source=NativeWorkbench.restorableURL(pane.web.url,service:pane.serviceHome) {
                let session=nyraStatus.alias(kinds[index]+"|"+source.absoluteString)
                if paneActivities[index]?.session != session { paneActivityRunIDs.removeValue(forKey:index);paneActivities[index]=PaneActivity(session:session,task:nil,state:"activity_unknown",at:now,reason:"PAGE_UNAVAILABLE") }
                guard !paneObservationPending.contains(index) else {continue}
                paneObservationPending.insert(index)
                pane.providerSnapshot { [weak self,weak pane] value in
                    guard let self=self else{return};self.paneObservationPending.remove(index)
                    guard let pane=pane,self.webPanes[index] === pane,self.kinds[index] != "Codex",NativeWorkbench.restorableURL(pane.web.url,service:pane.serviceHome)==source else{return}
                    let observed=value["state"] as? String ?? "unknown"
                    pane.reconcileAccessNotice(observed)
                    let state=["idle","running","waiting_user"].contains(observed) ? observed : "activity_unknown"
                    let reported=value["reason"] as? String ?? "OBSERVER_UNAVAILABLE"
                    let reason=reported.range(of:"^[A-Z0-9_]{1,80}$",options:.regularExpression) != nil ? reported : "OBSERVER_UNAVAILABLE"
                    let activityID=value["activityID"] as? String ?? ""
                    if state=="running",!activityID.isEmpty {self.paneActivityRunIDs[index]=self.nyraStatus.alias(session+"|"+activityID)}
                    self.paneActivityTokens[index]=activityID
                    if state=="idle" {self.paneActivityRunIDs.removeValue(forKey:index)}
                    self.paneActivities[index]=PaneActivity(session:session,task:self.paneActivityRunIDs[index],state:state,at:ProcessInfo.processInfo.systemUptime,reason:reason)
                    self.publishPaneActivity()
                }
            } else { paneActivities[index]=PaneActivity(session:"unselected",task:nil,state:"activity_unknown",at:now,reason:"PAGE_UNAVAILABLE") }
        }
        publishPaneActivity()
    }
    static func companionTitle(_ title:String?) -> String? {
        guard let title=title else{return nil}
        let value=title.components(separatedBy:.whitespacesAndNewlines).filter{!$0.isEmpty}.joined(separator:" ")
        guard !value.isEmpty,value.rangeOfCharacter(from:.controlCharacters)==nil,
              !value.hasPrefix("/"),!value.hasPrefix("~"),!value.contains("://") else{return nil}
        return String(value.prefix(90))
    }
    func publishPaneActivity() {
        var aggregate=PaneActivity.aggregate(paneActivities)
        // Between confirmed replies and the next dispatch this is scheduling,
        // not inference. Read-only inspection alone never creates activity.
        if aggregate.state=="idle",dialogue?.state=="running" {aggregate=("queued","both")}
        let identity=(0...1).map { paneActivities[$0]?.session ?? "unknown" }.joined(separator:"|")
        let active=(0...1).compactMap { paneActivities[$0]?.task }.joined(separator:"|")
        let checks=(0...1).compactMap { paneActivities[$0]?.fresh == true ? paneActivities[$0]?.evidence : nil }.joined(separator:"|")
        // Only currently displayed, fresh active-pane titles. Never prompts,
        // replies, attachments, URLs, account identity or historical titles.
        let labels:[[String:String]]=(0...1).compactMap { index in
            guard let activity=paneActivities[index],activity.fresh,["running","queued","waiting_user"].contains(activity.state) else{return nil}
            let title:String?
            if kinds[index]=="Codex",let client=codex {
                title=client.threadRows.first(where:{$0["id"] as? String==client.threadID})?["name"] as? String
            } else {title=webPanes[index]?.web.title}
            let fallback=activity.state=="waiting_user" ? "等待你的操作 / Waiting for you" : "当前任务 / Current task"
            return ["side":index==0 ? "left":"right","provider":kinds[index],"title":Self.companionTitle(title) ?? fallback]
        }
        _ = nyraPublicTasks()
        nyraStatus.observe(session:nyraStatus.alias(identity),task:active.isEmpty ? nil : nyraStatus.alias(active),state:aggregate.state,source:"twos_runtime",ownerEvidence:aggregate.state=="verified_success" && !checks.isEmpty ? nyraStatus.alias(checks) : nil,side:aggregate.side,panes:PaneActivity.observations(paneActivities),labels:labels)
    }
    @discardableResult func persistWebTransfers() -> Bool {
        guard !webLedgerError else { return false }
        do {
            try NativeWorkbench.safeDirectory(preferences)
            let file = preferences.appendingPathComponent("web-handoff-receipts.json")
            try JSONEncoder().encode(webTransfers).write(to: file, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
            return true
        } catch { webLedgerError = true; return false }
    }
    func publishWebTransfer(_ id: String) {
        guard let record = webTransfers.first(where: { $0.id == id }) else { return }
        webCache.values.forEach { $0.showHandoffProgress(record.card) }
        if kinds[record.targetPane] == record.provider { webPanes[record.targetPane]?.showNotice(record.provider + " · " + translate(record.statusLabel)) }
        refreshWebHistory()
        refreshDialogueUI()
        refreshNyraStatus()
    }
    @objc func showWebHistory() {
        if handoffWindow == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 520), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            w.isReleasedWhenClosed = false; w.delegate = self; handoffWindow = w
            handoffPicker.target = self; handoffPicker.action = #selector(historySelectionChanged)
            let scroll = NSScrollView(); scroll.hasVerticalScroller = true
            handoffDetail.isEditable = false; handoffDetail.isVerticallyResizable = true; handoffDetail.autoresizingMask = [.width]; scroll.documentView = handoffDetail
            let check = NSButton(title: translate("Check delivery"), target: self, action: #selector(checkHistoryDelivery))
            let resume = NSButton(title: translate("Resume saved handoff…"), target: self, action: #selector(resumeHistoryDelivery))
            let cancel = NSButton(title: translate("Cancel unsent handoff"), target: self, action: #selector(cancelHistoryDelivery))
            let reply = NSButton(title: translate("Send reply to the other pane"), target: self, action: #selector(sendHistoryReply))
            historyButtons = [(check, "Check delivery"), (resume, "Resume saved handoff…"), (cancel, "Cancel unsent handoff"), (reply, "Send reply to the other pane")]
            let buttons = NSStackView(views: [check, resume, cancel, reply]); buttons.spacing = 10
            let reopen = NSButton(title:translate("Open bound conversations"),target:self,action:#selector(openHistoryConversations))
            historyReopenButton=reopen
            let layout = NSStackView(views: [handoffPicker, reopen, scroll, buttons]); layout.orientation = .vertical; layout.alignment = .leading; layout.spacing = 12; layout.translatesAutoresizingMaskIntoConstraints = false
            w.contentView!.addSubview(layout)
            NSLayoutConstraint.activate([layout.leadingAnchor.constraint(equalTo: w.contentView!.leadingAnchor, constant: 16),layout.trailingAnchor.constraint(equalTo: w.contentView!.trailingAnchor, constant: -16),layout.topAnchor.constraint(equalTo: w.contentView!.topAnchor, constant: 16),layout.bottomAnchor.constraint(equalTo: w.contentView!.bottomAnchor, constant: -16),scroll.widthAnchor.constraint(equalTo: layout.widthAnchor),handoffPicker.widthAnchor.constraint(equalTo: layout.widthAnchor)])
        }
        handoffWindow?.title = translate("Handoff history"); refreshWebHistory(); handoffWindow?.center(); handoffWindow?.makeKeyAndOrderFront(nil)
    }
    var selectedWebReceipt: WebHandoffReceipt? {
        guard let id = handoffPicker.selectedItem?.representedObject as? String else { return nil }
        return webTransfers.first { $0.id == id }
    }
    func refreshWebHistory() {
        guard handoffWindow != nil else { return }
        let selected = handoffPicker.selectedItem?.representedObject as? String
        handoffPicker.removeAllItems()
        for record in webTransfers.reversed() {
            let item = NSMenuItem(title: record.provider + " · " + translate(record.statusLabel) + " · " + record.id.prefix(8), action: nil, keyEquivalent: "")
            item.representedObject = record.id; handoffPicker.menu?.addItem(item)
            if record.id == selected { handoffPicker.select(item) }
        }
        historySelectionChanged()
    }
    @objc func historySelectionChanged() {
        historyReopenButton?.title=translate("Open bound conversations")
        historyReopenButton?.isEnabled=selectedWebReceipt != nil && dialogue?.state != "running"
        historyButtons.forEach { $0.0.isEnabled = false }
        guard let record = selectedWebReceipt else { handoffDetail.string = translate("No website handoffs yet."); return }
        let onTarget = currentTargetMatches(record)
        historyButtons.first?.0.isEnabled = canInspectCurrentTarget(record)
        if historyButtons.count >= 3 {
            historyButtons[1].0.isEnabled = onTarget && record.mayHaveSent != true && ["draft", "queued", "queue_paused"].contains(record.state)
            historyButtons[2].0.isEnabled = record.mayHaveSent != true && !["cancelled", "sent", "reply", "sending", "unknown"].contains(record.state)
        }
        if historyButtons.count > 3 { historyButtons[3].0.isEnabled = onTarget && record.state == "reply" && record.result != nil }
        handoffDetail.string = record.provider + " · " + translate(record.statusLabel) + "\n\n" + record.source + "\n→ " + (record.resolvedURL ?? record.targetURL) + "\n\nID: " + record.id + "\nSHA-256: " + record.hash + "\n\n" + translate("Selected content") + "\n" + record.text + "\n\n" + translate("Website reply") + "\n" + (record.result ?? "—")
        if let inspection = record.inspection { handoffDetail.string = translate("Delivery check") + ": " + translate(inspection) + "\n\n" + handoffDetail.string }
    }
    func companionTargetMatches(_ r: WebHandoffReceipt) -> Bool {
        guard let target=r.nyraTarget else{return true}
        guard let task=nyraTask(r.targetPane) else{return false}
        return task["target"] as? String==target && task["fresh"] as? Bool==true &&
            r.nyraActivity==paneActivityTokens[r.targetPane]
    }
    func currentTargetMatches(_ r: WebHandoffReceipt) -> Bool {
        guard kinds[r.targetPane] == r.provider, let pane = webPanes[r.targetPane] else { return false }
        return NativeWorkbench.restorableURL(pane.web.url, service: pane.serviceHome)?.absoluteString == (r.resolvedURL ?? r.targetURL)
    }
    func canInspectCurrentTarget(_ r: WebHandoffReceipt) -> Bool {
        if currentTargetMatches(r) { return true }
        // After an uncertain first send, the provider may have assigned a chat
        // URL before TWOS received its acknowledgement. Read-only reconciliation
        // may search that currently open same-service chat for the exact unique
        // marker and full body. This never enables resume/send or changes an
        // already established conversation binding.
        guard (r.resolvedURL == nil || r.resolvedURL == r.targetURL), r.mayHaveSent == true,
              ["unknown","sending","sent","reply"].contains(r.state), kinds[r.targetPane] == r.provider,
              let pane=webPanes[r.targetPane],let original=URL(string:r.targetURL),
              ["","/","/new"].contains(original.path),
              let current=NativeWorkbench.restorableURL(pane.web.url,service:pane.serviceHome) else { return false }
        return current.scheme==original.scheme && current.host==original.host && current.port==original.port
    }
    @objc func checkHistoryDelivery() {
        guard let r = selectedWebReceipt, canInspectCurrentTarget(r), let pane = webPanes[r.targetPane] else { handoffDetail.string = translate("Open the original destination pane to check this handoff. Nothing will be resent."); return }
        inspectWebTransfer(r.id, target: pane)
    }
    @objc func openHistoryConversations() {
        guard let r=selectedWebReceipt,dialogue?.state != "running",
              let target=webPanes[r.targetPane],let source=webPanes[1-r.targetPane],
              kinds[r.targetPane]==r.provider,
              let to=NativeWorkbench.restorableURL(URL(string:r.resolvedURL ?? r.targetURL),service:target.serviceHome),
              let from=NativeWorkbench.restorableURL(URL(string:r.source),service:source.serviceHome) else {
            handoffDetail.string=translate("Pause automatic exchange and select the original two services before opening these conversations. Nothing was sent.");return
        }
        let pages=[source,target],urls=[from,to],before=pages.map{$0.web.url}
        var checks=0,canNavigate=true
        for pane in pages {
            pane.web.evaluateJavaScript("window.twosProviderDOM?.navigationSafety?.()",in:nil,in:NativeWorkbench.handoffWorld) { [weak self] result in
                guard let self=self else{return}
                if case .success(let raw)=result,let state=raw as? [String:Any],state["state"] as? String=="idle",state["hasDraft"] as? Bool==false {} else {canNavigate=false}
                checks += 1;guard checks==2 else{return}
                guard self.selectedWebReceipt?.id==r.id,self.dialogue?.state != "running",
                      self.webPanes[r.targetPane] === target,self.webPanes[1-r.targetPane] === source,
                      pages.enumerated().allSatisfy({$0.element.web.url==before[$0.offset]}),canNavigate else {
                    self.handoffDetail.string=self.translate("Finish the current reply and preserve or clear website drafts before opening bound conversations. No page was changed and nothing was sent.");return
                }
                for (index,page) in pages.enumerated() where page.web.url != urls[index] {page.web.load(URLRequest(url:urls[index]))}
                self.handoffDetail.string=self.translate("Opening the recorded conversations. This only navigates; check delivery after they finish loading. Nothing was sent.")
            }
        }
    }
    @objc func sendHistoryReply() { if let r = selectedWebReceipt { sendRecordedWebReply(r.id) } }
    func sendRecordedWebReply(_ id: String) {
        guard let record = webTransfers.first(where: { $0.id == id }), record.state == "reply", let reply = record.result,
              currentTargetMatches(record), let origin = webPanes[record.targetPane],
              let target = webPanes[1-record.targetPane], NativeWorkbench.restorableURL(target.web.url, service:target.serviceHome)?.absoluteString == record.source,
              let source = URL(string:record.resolvedURL ?? record.targetURL) else {
            webPanes.values.forEach { $0.showNotice("Open both original conversations and check the completed reply before sending it back. Nothing was sent.") }; return
        }
        // Reconcile the exact parent receipt before sending the complete answer.
        // A newer answer or changed conversation never substitutes for it.
        origin.webTransfer(record.request(inspectOnly:true)) { [weak self, weak origin] value in
            guard let self = self, value["state"] as? String == "reply", value["reply"] as? String == reply,
                  self.currentTargetMatches(record), NativeWorkbench.restorableURL(target.web.url, service:target.serviceHome)?.absoluteString == record.source else {
                origin?.showNotice("The completed reply could not be reconciled. Nothing was sent; check delivery again."); return
            }
            self.handoff(reply, source:source, from:record.targetPane, message:"reply:" + record.id + ":" + NativeCodex.digest(Data(reply.utf8)))
        }
    }
    @objc func cancelHistoryDelivery() {
        guard let r = selectedWebReceipt, r.mayHaveSent != true, ["queued","queue_paused","busy","draft","login","verification","not_loaded","draft_conflict","unsupported","target_changed"].contains(r.state), let i = webTransfers.firstIndex(where: { $0.id == r.id }) else { return }
        activeWebQueues.remove(r.id); transferTimers[r.id]?.invalidate(); webTransfers[i].state = "cancelled"
        if persistWebTransfers() { publishWebTransfer(r.id) }
    }
    @objc func resumeHistoryDelivery() {
        guard let r = selectedWebReceipt, r.mayHaveSent != true, ["draft", "queued", "queue_paused"].contains(r.state), currentTargetMatches(r), let source = URL(string: r.source) else { return }
        handoffWindow?.orderOut(nil); handoff(r.text, source: source, from: 1-r.targetPane, message: r.message)
    }
    func handoff(_ text: String, source: URL, from index: Int, message: String = "") {
        if dialogue?.state == "running" {
            pauseDialogue("Manual handoff requested. Automatic exchange paused; review the target and send again.")
            webPanes[index]?.showNotice("Manual handoff requested. Automatic exchange paused; review the target and send again.")
            return
        }
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, text.utf8.count <= 200_000,
              let origin = webPanes[index], NativeWorkbench.restorableURL(origin.web.url, service: origin.serviceHome) == source else { return }
        let destination = 1-index
        if kinds[destination] == "Codex" { codex?.stage(text, source: source, message: message); return }
        guard let target = webPanes[destination],
              let url = NativeWorkbench.restorableURL(target.web.url, service: target.serviceHome) else {
            origin.showNotice("The destination is not ready. Load the target conversation first."); return
        }
        let provider = kinds[destination], binding = routeSignature(index)
        guard ["ChatGPT", "DeepSeek", "Claude"].contains(provider) else { origin.showNotice("This website has no verified sending adapter. Nothing was sent."); return }
        let hash = SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
        var resumedDraft: WebHandoffReceipt?
        if let previous = webTransfers.last(where: { $0.source == source.absoluteString && ($0.files ?? []) == (webFileSelections[index] ?? []) && ($0.message == message || $0.legacyMessageIdentity) && $0.hash == hash && $0.provider == provider && $0.targetPane == destination && ($0.resolvedURL ?? $0.targetURL) == url.absoluteString && ($0.mayHaveSent == true || !["cancelled", "target_changed", "rejected", "verification", "login", "not_loaded", "busy", "draft_conflict", "unsupported"].contains($0.state)) }) {
            if previous.legacyMessageIdentity && previous.message != message {
                publishWebTransfer(previous.id);inspectWebTransfer(previous.id,target:target)
                origin.showNotice("A matching older receipt has no stable message identity. Nothing is resent; inspect Handoff history.");return
            }
            if ["draft", "queue_paused", "queued"].contains(previous.state), previous.mayHaveSent != true { resumedDraft = previous }
            else {
                publishWebTransfer(previous.id)
                inspectWebTransfer(previous.id, target: target)
                origin.showNotice("This handoff is already recorded. Its delivery is being checked; it will not be sent twice."); return
            }
        }
        guard !webLedgerError else { origin.showNotice("Handoff history is unavailable. Sending is blocked to prevent a duplicate."); return }
        let record = resumedDraft ?? WebHandoffReceipt(source: source.absoluteString, message: message, text: text, hash: hash, provider: provider, targetPane: destination, targetURL: url.absoluteString, binding: binding, files:webFileSelections[index] ?? [])
        // The explicit card/toolbar click authorizes this frozen text and exact selected files.
        // handoff. Do not ask for the same permission in a second modal sheet.
        // Website preflight still refuses login/challenges and existing drafts.
        guard routeSignature(index) == binding,
              NativeWorkbench.restorableURL(target.web.url, service: target.serviceHome) == url else {
            origin.showNotice("The destination changed. Review the current destination and send again."); return
        }
        if let old = webTransfers.firstIndex(where: { $0.id == record.id }) {
            guard ["draft", "queue_paused", "queued"].contains(webTransfers[old].state), webTransfers[old].mayHaveSent != true else { return }
            webTransfers[old].resumeDraft = webTransfers[old].state == "draft"
            webTransfers[old].state = "preparing"
        } else { webTransfers.append(record) }
        guard persistWebTransfers() else { origin.showNotice("Could not save the handoff intent. Nothing was sent."); return }
        submitWebTransfer(record.id, target: target)
    }
    func submitWebTransfer(_ id: String, target: NativeWorkbench) {
        guard let i = webTransfers.firstIndex(where: { $0.id == id }), webTransfers[i].state == "preparing" else { return }
        let record = webTransfers[i]
        guard companionTargetMatches(record), kinds[record.targetPane] == record.provider, webPanes[record.targetPane] === target,
              NativeWorkbench.restorableURL(target.web.url, service: target.serviceHome)?.absoluteString == record.targetURL else {
            webTransfers[i].state = "target_changed"; _ = persistWebTransfers(); publishWebTransfer(id); return
        }
        var request=record.request(inspectOnly:false)
        do { request["files"]=try payloadFiles(record.files ?? []) }
        catch { webTransfers[i].state="unsupported";webTransfers[i].inspection="ATTACHMENT_MISSING_OR_CHANGED";_ = persistWebTransfers();publishWebTransfer(id);return }
        webTransfers[i].state = "sending"
        webRuntimeObservations[id] = ("sending", ProcessInfo.processInfo.systemUptime)
        webTransfers[i].mayHaveSent = true // Persist before crossing the website boundary.
        guard persistWebTransfers() else { return }
        publishWebTransfer(id)
        target.webTransfer(request) { [weak self, weak target] response in
            self?.applyWebResponse(id, response: response, dispatchResponse: true)
            if let target = target, ["sent", "unknown"].contains(response["state"] as? String ?? "") { self?.observeWebTransfer(id, target: target) }
        }
    }
    func applyWebResponse(_ id: String, response: [String: Any], dispatchResponse: Bool = false) {
        guard let i = webTransfers.firstIndex(where: { $0.id == id }) else { return }
        let allowed = ["sent", "reply", "generation_stopped", "unknown", "draft", "verification", "login", "busy", "not_loaded", "target_changed", "unsupported", "draft_conflict", "provider_limited"]
        var state = response["state"] as? String ?? "unknown"
        if let reason=response["reason"] as? String {
            webTransfers[i].inspection=reason
            if dispatchResponse {webTransfers[i].dispatchReason=reason}
        }
        guard allowed.contains(state) else { return }
        if webTransfers[i].dialogueID != nil, ["verification","login","provider_limited"].contains(state) {
            pauseDialogue(state == "provider_limited" ? "The provider reported a service limit or capacity issue. No next message is sent." : "Login or human verification is required. No next message is sent.")
        }
        // Activity evidence is separate from the irreversible delivery receipt.
        // A failed read must invalidate animation liveness without erasing SENT.
        if webRuntimeObservations.count > 128 { webRuntimeObservations.removeAll() }
        webRuntimeObservations[id] = (state, ProcessInfo.processInfo.systemUptime)
        // Only the original call can prove a pre-send refusal. Read-only polling
        // after SPA navigation must never turn uncertain delivery into "not sent".
        if !dispatchResponse && !["sent", "reply", "generation_stopped"].contains(state) {
            // A read does not send. Preserve an original, explicit pre-send
            // refusal; otherwise a harmless Check would disable its draft
            // recovery/cancel actions. An uncertain dispatch remains unknown.
            let prior = webTransfers[i]
            state = prior.mayHaveSent == false && !["sending", "sent", "reply", "unknown"].contains(prior.state) ? prior.state : "unknown"
        }
        if dispatchResponse && !["sent", "reply", "generation_stopped", "unknown"].contains(state) { webTransfers[i].mayHaveSent = false }
        if ["sent", "reply", "generation_stopped"].contains(state) { webTransfers[i].mayHaveSent = true }
        if dispatchResponse && state == "busy" { state = "queued" }
        // A later inspection failure cannot erase an established send receipt.
        if !["reply","generation_stopped"].contains(webTransfers[i].state) && (webTransfers[i].state != "sent" || ["reply","generation_stopped"].contains(state)) { webTransfers[i].state = state }
        if ["sent","reply","generation_stopped"].contains(state), let destination = response["conversationURL"] as? String, let original = URL(string: webTransfers[i].targetURL),
           let actual = NativeWorkbench.restorableURL(URL(string: destination), service: original) { webTransfers[i].resolvedURL = actual.absoluteString }
        if let reply = response["reply"] as? String, state == "reply", reply.utf8.count <= 200_000 {
            if let original=webTransfers[i].result, original != reply {
                webTransfers[i].inspection="COMPLETE_REPLY_CHANGED · original reply preserved"
                if webTransfers[i].dialogueID != nil {pauseDialogue("The previously complete reply changed. Review it before continuing.")}
            } else {
                webTransfers[i].result=reply;webTransfers[i].resultHash=NativeCodex.digest(Data(reply.utf8))
                webTransfers[i].replyMessage=response["replyMessage"] as? String
            }
        }
        webTransfers[i].updatedAt = Date().timeIntervalSince1970
        if persistWebTransfers() { publishWebTransfer(id) }
        if state == "generation_stopped", dialogue?.pendingID == id, dialogue?.state == "running" {
            stopDialogueWithReason("The website confirms that generation was interrupted. Future exchanges cancelled.")
        }
        if state == "queued", webTransfers[i].dialogueID != nil {
            webTransfers[i].state="queue_paused";_ = persistWebTransfers();publishWebTransfer(id)
            pauseDialogue("The participant is busy. Wait for its current work, then review the pending exchange.")
        } else if state == "queued", let target = webPanes[webTransfers[i].targetPane] { observeQueuedTransfer(id, target: target) }
    }
    func observeQueuedTransfer(_ id: String, target: NativeWorkbench) {
        activeWebQueues.insert(id); transferTimers[id]?.invalidate(); var reads = 0; var inspecting = false
        transferTimers[id] = Timer.scheduledTimer(withTimeInterval: 3, repeats: true) { [weak self, weak target] timer in
            guard let self = self, let target = target, let i = self.webTransfers.firstIndex(where: { $0.id == id }), self.webTransfers[i].state == "queued", self.activeWebQueues.contains(id) else { timer.invalidate(); return }
            let record = self.webTransfers[i]; reads += 1
            guard reads <= 100, self.companionTargetMatches(record), self.kinds[record.targetPane] == record.provider, self.webPanes[record.targetPane] === target,
                  NativeWorkbench.restorableURL(target.web.url, service: target.serviceHome)?.absoluteString == record.targetURL else {
                timer.invalidate(); self.activeWebQueues.remove(id); self.webTransfers[i].state = "queue_paused"; if self.persistWebTransfers() { self.publishWebTransfer(id) }; return
            }
            let earlier = self.webTransfers.contains { $0.id != id && $0.provider == record.provider && $0.targetURL == record.targetURL && $0.createdAt < record.createdAt && ["queued","sending","unknown","sent","queue_paused"].contains($0.state) }
            guard !earlier && !inspecting else { return }; inspecting = true
            var request = record.request(inspectOnly: false); request["preflightOnly"] = true
            target.webTransfer(request) { [weak self, weak target] response in
                inspecting = false
                guard let self = self, let target = target, self.webTransfers[i].id == id, self.webTransfers[i].state == "queued", self.activeWebQueues.contains(id) else { return }
                let state = response["state"] as? String ?? "unknown"
                if state == "busy" { return }
                timer.invalidate(); self.activeWebQueues.remove(id)
                if state == "ready" { self.webTransfers[i].state = "preparing"; if self.persistWebTransfers() { self.submitWebTransfer(id, target: target) } }
                else if ["sent","reply"].contains(state) { self.applyWebResponse(id, response: response) }
                else { self.webTransfers[i].state = "queue_paused"; if self.persistWebTransfers() { self.publishWebTransfer(id) } }
            }
        }
    }
    func inspectWebTransfer(_ id: String, target: NativeWorkbench) {
        guard let i = webTransfers.firstIndex(where: { $0.id == id }), !inspectionsInFlight.contains(id) else { return }
        let record = webTransfers[i]
        inspectionsInFlight.insert(id); webTransfers[i].inspection = "checking"; publishWebTransfer(id)
        target.webTransfer(record.request(inspectOnly: true)) { [weak self] value in
            guard let self = self else { return }; self.inspectionsInFlight.remove(id)
            if let i = self.webTransfers.firstIndex(where: { $0.id == id }) {
                self.webTransfers[i].inspection = (value["state"] as? String ?? "unknown") + (value["reason"].map { " · \($0)" } ?? "")
                self.webTransfers[i].inspectedAt = Date().timeIntervalSince1970
            }
            self.applyWebResponse(id, response:value)
        }
    }
    func observeWebTransfer(_ id: String, target: NativeWorkbench) {
        transferTimers[id]?.invalidate()
        var reads = 0
        transferTimers[id] = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self, weak target] timer in
            reads += 1
            guard let self = self, let target = target, reads <= 90,
                  let record = self.webTransfers.first(where: { $0.id == id }), !["reply","generation_stopped"].contains(record.state),
                  self.webPanes[record.targetPane] === target, self.kinds[record.targetPane] == record.provider else { timer.invalidate(); return }
            self.inspectWebTransfer(id, target: target)
        }
    }
    func bringBack(_ text: String, source: URL) {
        guard let target = webPanes.first(where: { kinds[$0.key] != "Codex" && NativeWorkbench.restorableURL($0.value.web.url, service: $0.value.serviceHome) == source })?.value else {
            codex?.notice("The original discussion is not open. Return to it in the other pane, then bring the result back."); return
        }
        target.placeDraft(text, expectedSource: source) { [weak self] ok in
            if ok { self?.codex?.notice("The result is now in the original discussion composer. Review and send it there.") }
        }
    }
}

// TWOS control-plane evidence; never written into provider histories/databases.
struct WebHandoffReceipt: Codable {
    var legacyMessageIdentity: Bool {
        message == "latest-rendered-reply" || message.range(of:"^rendered-assistant-[0-9]+$",options:.regularExpression) != nil
    }
    var id = UUID().uuidString
    let source: String
    let message: String
    let text: String
    let hash: String
    let provider: String
    let targetPane: Int
    let targetURL: String
    let binding: String
    var dialogueID: String?
    var nyraTarget: String?
    var nyraActivity: String?
    var files: [WebTransferFile]?
    var resolvedURL: String?
    var resumeDraft: Bool?
    var mayHaveSent: Bool?
    var state = "preparing"
    var result: String?
    var resultHash: String?
    var replyMessage: String?
    var inspection: String?
    var dispatchReason: String?
    var inspectedAt: TimeInterval?
    var createdAt = Date().timeIntervalSince1970
    var updatedAt = Date().timeIntervalSince1970
    var statusLabel: String {
        switch state {
        case "reply": return "Reply received. No local file was created."
        case "sent": return "The website contains this exact instruction."
        case "generation_stopped": return "Instruction received; the website confirms that its reply was interrupted. No complete reply is forwarded."
        case "draft": return "Draft only. Review and send it in the website."
        case "verification": return "Complete the website's human verification. Nothing was sent."
        case "login": return "Sign in to this website. Nothing was sent."
        case "provider_limited": return "The provider reported a limit or capacity issue. Inspect the website notice before continuing."
        case "busy": return "The target is replying. This handoff is saved and has not been sent."
        case "queued": return "Queued for this exact website conversation. Switches or login changes pause dispatch."
        case "queue_paused": return "Queue paused. Open the original conversation and explicitly resume from Handoff history."
        case "cancelled": return "Unsent handoff cancelled. Existing website drafts are preserved."
        case "target_changed": return "The destination changed. Nothing was sent."
        case "draft_conflict": return "The target has an existing draft. It has been preserved."
        case "unsupported":
            if (dispatchReason ?? inspection)?.hasPrefix("EXACT_FILE_UPLOAD_CONTROL_UNAVAILABLE") == true {return "The website attachment control is unavailable or ambiguous. Your draft is preserved; nothing was sent."}
            return "No verified website send control is available. Nothing was sent."
        case "sending": return "Sending the confirmed instruction."
        default: return "Delivery needs verification. It will not be repeated automatically."
        }
    }
    func request(inspectOnly: Bool) -> [String: Any] {
        var value: [String: Any] = ["id": id, "text": text, "hash": hash, "provider": provider, "targetURL": resolvedURL ?? targetURL, "inspectOnly": inspectOnly, "draftOnly": false, "resumeDraft": resumeDraft == true]
        if let activity=nyraActivity {value["expectedActivity"]=activity}
        // Reconciliation needs the original attachment identity to distinguish
        // website-added file captions from the exact submitted body. Metadata
        // only: observing delivery never rereads or uploads file bytes.
        if inspectOnly {
            value["files"] = (files ?? []).map { ["id":$0.id,"name":$0.name,"mime":$0.mime,"size":$0.size,"hash":$0.hash] as [String:Any] }
        }
        return value
    }
    var card: [String: Any] {
        ["id": id, "source": source, "message": message, "hash": hash, "binding":binding, "provider": provider, "targetURL": resolvedURL ?? targetURL, "state": state, "createdAt": createdAt, "retryable": mayHaveSent != true && ["draft", "login", "verification", "busy", "not_loaded", "draft_conflict", "unsupported", "target_changed"].contains(state), "inspectable": mayHaveSent == true || state == "unknown", "result": result ?? "", "error": statusLabel, "inspection": inspection ?? "", "attachments": (files ?? []).map { ["id":$0.id,"name":$0.name,"mime":$0.mime,"size":$0.size,"sha256":$0.hash] as [String:Any] }]
    }
}

// Visibility control uses the pinned helper, or an already-running compatible
// signed standalone Nyra. A standalone display is not claimed as a task binding.
final class NativeNyra: NSObject {
    let stateRoot: URL
    var isolated: Bool { CommandLine.arguments.contains("--diagnostic-root") }
    // Diagnostic sessions may select one exact signed standalone candidate.
    // They must never discover or write to the Owner's normal Nyra profile.
    static func diagnosticStandaloneURL(_ arguments: [String]) -> URL? {
        guard let rootIndex=arguments.firstIndex(of:"--diagnostic-root"),rootIndex+1<arguments.count,
              arguments[rootIndex+1].hasPrefix("/"),
              !arguments[rootIndex+1].split(separator:"/").contains(".."),
              let index=arguments.firstIndex(of:"--diagnostic-nyra-app"),index+1<arguments.count else{return nil}
        let path=arguments[index+1]
        guard path.hasPrefix("/"),!path.split(separator:"/").contains(".."),path.hasSuffix(".app") else{return nil}
        return URL(fileURLWithPath:path,isDirectory:true).standardizedFileURL
    }
    var diagnosticStandaloneURL: URL? { Self.diagnosticStandaloneURL(CommandLine.arguments) }
    var standaloneStateRoot: URL {
        isolated ? stateRoot.deletingLastPathComponent().appendingPathComponent("standalone-nyra",isDirectory:true)
                 : FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("Nyra")
    }
    static let standaloneID = "com.tianma.nyra"
    static func compatibleStandalone(_ app: NSRunningApplication) -> Bool {
        guard app.bundleIdentifier == standaloneID, let url = app.bundleURL,
              let bundle = Bundle(url:url), [1,2].contains(bundle.object(forInfoDictionaryKey:"NyraVisibilityProtocol") as? Int ?? 0) else { return false }
        var code: SecStaticCode?; var requirement: SecRequirement?
        guard SecStaticCodeCreateWithPath(url as CFURL,[],&code) == errSecSuccess,
              SecRequirementCreateWithString("anchor apple generic and certificate leaf[subject.OU] = BZJWQJ352K" as CFString,[],&requirement) == errSecSuccess,
              let code = code, let requirement = requirement else { return false }
        return SecStaticCodeCheckValidity(code,SecCSFlags(rawValue:kSecCSStrictValidate),requirement) == errSecSuccess
    }
    static func signedCodeHash(_ url:URL) -> Data? {
        var code:SecStaticCode?;var info:CFDictionary?
        guard SecStaticCodeCreateWithPath(url as CFURL,[],&code)==errSecSuccess,let code=code,
              SecStaticCodeCheckValidity(code,SecCSFlags(rawValue:kSecCSStrictValidate),nil)==errSecSuccess,
              SecCodeCopySigningInformation(code,[],&info)==errSecSuccess else{return nil}
        return (info as? [String:Any])?[kSecCodeInfoUnique as String] as? Data
    }
    private var standaloneCache:NSRunningApplication?
    private var standaloneCheckKey=""
    private var standaloneCheckedAt=0.0
    private var standaloneChecking=false
    private var standaloneGeneration=0
    private var authorizationGeneration=0
    private var authorizationPending=false
    private var authorizedVisibilityRequest:Bool?
    var standaloneCandidates:[NSRunningApplication] {
        if isolated && diagnosticStandaloneURL == nil {return []}
        return NSRunningApplication.runningApplications(withBundleIdentifier:Self.standaloneID).filter {
            !$0.isTerminated && (!isolated || $0.bundleURL?.standardizedFileURL == diagnosticStandaloneURL)
        }
    }
    func discoverStandalone() {
        let candidates=standaloneCandidates
        let key=candidates.map{"\($0.processIdentifier)|\($0.launchDate?.timeIntervalSince1970 ?? 0)|\($0.bundleURL?.path ?? "")"}.joined(separator:";")
        let now=ProcessInfo.processInfo.systemUptime
        if key != standaloneCheckKey {
            standaloneGeneration+=1;standaloneChecking=false;standaloneCache=nil;standaloneCheckedAt=0;standaloneCheckKey=key
        }
        guard !candidates.isEmpty else{standaloneCache=nil;return}
        guard !standaloneChecking,now-standaloneCheckedAt>=10 else{return}
        standaloneChecking=true;let generation=standaloneGeneration
        DispatchQueue.global(qos:.utility).async{[weak self] in
            // Strict signature validation can read the whole bundle. Never do it
            // in a computed UI property or a mouse/visibility callback.
            let selected=candidates.first{Self.compatibleStandalone($0)}
            DispatchQueue.main.async{
                guard let self=self,self.standaloneGeneration==generation else{return}
                self.standaloneChecking=false;self.standaloneCheckedAt=ProcessInfo.processInfo.systemUptime
                self.standaloneCache=selected?.isTerminated==false ? selected:nil
                self.refresh()
            }
        }
    }
    var standalone: NSRunningApplication? {
        guard let cached=standaloneCache,!cached.isTerminated,
              !isolated || cached.bundleURL?.standardizedFileURL == diagnosticStandaloneURL else{return nil}
        return cached
    }
    var targetURL: URL? { standalone?.bundleURL ?? helperURL }
    var targetStateRoot: URL {
        standalone != nil ? standaloneStateRoot : stateRoot
    }
    var targetProcesses: [NSRunningApplication] {
        if let app = standalone { return [app] }
        return NSRunningApplication.runningApplications(withBundleIdentifier:"com.tianma.workos.nyra").filter {
            !$0.isTerminated && (!isolated || $0.bundleURL?.standardizedFileURL == helperURL?.standardizedFileURL)
        }
    }
    var otherEmbeddedHelper: Bool {
        guard standalone == nil, let expected = helperURL else { return false }
        return NSRunningApplication.runningApplications(withBundleIdentifier:"com.tianma.workos.nyra").contains {
            !$0.isTerminated && $0.bundleURL?.standardizedFileURL != expected.standardizedFileURL
        }
    }
    let producerInstance: () -> String?
    let authorizeConsumer: (NSRunningApplication) throws -> Void
    let changed: ([String: Any]) -> Void
    var observer: NSObjectProtocol?
    var lifecycleObserver: NSObjectProtocol?
    var pending = false
    private(set) var controlFailure: String?
    private var visibilityCache: [String: Any]?
    private(set) var stateReadInFlight = false
    private var stateReadAgain = false
    var visibilityReader: (URL) -> [String: Any]? = NativeNyra.readVisibility
    static func readVisibility(_ file: URL) -> [String: Any]? {
        let fd = Darwin.open(file.path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK)
        guard fd >= 0 else { return nil }; defer { Darwin.close(fd) }
        var st = stat()
        guard fstat(fd, &st) == 0, st.st_uid == getuid(), st.st_mode & S_IFMT == S_IFREG,
              st.st_size > 0, st.st_size <= 16384 else { return nil }
        var bytes = [UInt8](repeating: 0, count: Int(st.st_size))
        guard Darwin.read(fd, &bytes, bytes.count) == bytes.count else { return nil }
        return (try? JSONSerialization.jsonObject(with: Data(bytes))) as? [String: Any]
    }
    func requestVisibilityRead() {
        guard !stateReadInFlight else { stateReadAgain = true; return }
        stateReadInFlight = true
        let selected = targetURL, file = targetStateRoot.appendingPathComponent("visibility-state.json"), reader = visibilityReader
        // macOS may hold open() while asking for directory access. Keep that
        // legitimate permission wait off the UI and status-producer queue.
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let value = reader(file)
            DispatchQueue.main.async {
                guard let self = self else { return }
                self.visibilityCache = selected?.standardizedFileURL == self.targetURL?.standardizedFileURL ? value : nil
                self.stateReadInFlight = false
                if self.stateReadAgain { self.stateReadAgain = false; self.requestVisibilityRead() }
                self.emitSnapshot()
            }
        }
    }
    private func emitSnapshot() {
        var state = snapshot()
        state["pending"] = pending || authorizationPending || stateReadInFlight || (standaloneChecking && standaloneCache==nil) || state["pending"] as? Bool == true
        changed(state)
    }
    var helperURL: URL? {
        let candidate = Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/TWOS Nyra.app")
        return FileManager.default.fileExists(atPath: candidate.path) ? candidate : nil
    }
    init(stateRoot: URL, producerInstance: @escaping () -> String? = { nil }, authorizeConsumer:@escaping (NSRunningApplication) throws -> Void = {_ in throw CocoaError(.fileReadNoPermission)}, changed: @escaping ([String: Any]) -> Void) {
        self.stateRoot = stateRoot; self.producerInstance = producerInstance; self.authorizeConsumer=authorizeConsumer;self.changed = changed; super.init()
        observer = DistributedNotificationCenter.default().addObserver(forName: Notification.Name("com.tianma.nyra.visibility"), object: nil, queue: .main) { [weak self] _ in self?.refresh() }
        lifecycleObserver = NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didTerminateApplicationNotification, object: nil, queue: .main) { [weak self] _ in
            // Refresh only our own recorded helper identity. A terminated
            // application's bundle metadata is not guaranteed to remain
            // available; filtering on it can leave a stale Hide button.
            DispatchQueue.main.async { self?.refresh() }
        }
    }
    deinit {
        if let observer = observer { DistributedNotificationCenter.default().removeObserver(observer) }
        if let lifecycleObserver = lifecycleObserver { NSWorkspace.shared.notificationCenter.removeObserver(lifecycleObserver) }
    }
    func snapshot() -> [String: Any] {
        var state=observedSnapshot()
        if state["observed"] as? Bool == true && state["fresh"] as? Bool == true { controlFailure=nil }
        if let error=controlFailure {state["reason"]=error;state["available"]=false}
        return state
    }
    // Pane freshness belongs to this authenticated producer's recent snapshot,
    // not merely to a still-alive consumer heartbeat or a saved event flag.
    static func currentPaneObservations(_ observations: [[String:Any]], connected: Bool, snapshotAge: Double?) -> [[String:Any]] {
        let snapshotIsCurrent = connected && (snapshotAge.map { $0.isFinite && (0..<7).contains($0) } ?? false)
        return observations.map { item in
            var observed = item
            observed["fresh"] = snapshotIsCurrent && item["fresh"] as? Bool == true
            return observed
        }
    }
    private func observedSnapshot() -> [String: Any] {
        if !standaloneCandidates.isEmpty,standalone==nil {return ["available":false,"observed":false,"binding":"NOT_CONNECTED","reason":standaloneChecking ? "NYRA_CHECKING_IDENTITY":"NYRA_VERSION_OR_IDENTITY_UNVERIFIED"]}
        guard let helper = targetURL else { return ["available": false, "visible": false, "reason": "NYRA_HELPER_NOT_BUNDLED", "binding": "NOT_CONNECTED"] }
        // Another installed copy is not our hidden pet. Do not present a Show
        // action that Launch Services could redirect to that unrelated process.
        if otherEmbeddedHelper { return ["available":false,"observed":false,"reason":"NYRA_OTHER_INSTALLATION_RUNNING","binding":"NOT_CONNECTED"] }
        // No helper means there is no live visibility evidence to read. Besides
        // rejecting old state from another build, this avoids an unnecessary
        // Downloads/TCC file prompt on workbench startup in engineering profiles.
        let observedProcesses=targetProcesses
        guard observedProcesses
            .contains(where: { !$0.isTerminated && $0.bundleURL?.standardizedFileURL == helper.standardizedFileURL }) else {
            return ["available": true, "visible": false, "observed": false, "binding": "NOT_CONNECTED"]
        }
        guard let state = visibilityCache, let pid = state["pid"] as? Int32,
              let process = observedProcesses.first(where:{$0.processIdentifier==pid}), !process.isTerminated,
              process.bundleURL?.standardizedFileURL == helper.standardizedFileURL,
              state["bundle"] as? String == helper.path else { return ["available": true, "visible": false, "observed": false, "binding": "NOT_CONNECTED"] }
        let now=ProcessInfo.processInfo.systemUptime
        let age=(state["heartbeatUptime"] as? Double).map{now-$0}
        let fresh=age.map{(0..<7).contains($0)} ?? false
        let connected = fresh && state["runBinding"] as? String == "CONNECTED_READONLY" && producerInstance() != nil && state["producerInstance"] as? String == producerInstance()
        var result: [String:Any] = ["available": true, "visible": state["visible"] as? Bool ?? false, "pending": state["pending"] as? Bool ?? false,
                "observed": true, "binding": connected ? "CONNECTED_READONLY" : "NOT_CONNECTED", "updatedAt": state["updatedAt"] ?? NSNull(),"fresh":fresh,"heartbeatAge":age as Any? ?? NSNull(),"consumerPID":pid]
        if !fresh {result["reason"]="NYRA_HEARTBEAT_STALE"}
        for key in ["consumerInstance","animation","frameAsset","frameCount","frameTimer","reduceMotion","lastStateChangeAt","paneObservations","taskState","activitySide","interactionError"] {result[key]=state[key]}
        let snapshotAge=(state["lastSnapshotUptime"] as? Double).flatMap { $0 > 0 ? now-$0 : nil }
        if let age=snapshotAge {result["snapshotAge"]=max(0,age)}
        result["paneObservations"]=Self.currentPaneObservations(state["paneObservations"] as? [[String:Any]] ?? [],connected:connected,snapshotAge:snapshotAge)
        return result
    }
    func refresh() {
        discoverStandalone()
        if controlFailure == "NYRA_OPEN_TARGET_MISMATCH" && !otherEmbeddedHelper { controlFailure=nil }
        // Observe the actual selected component, including a compatible signed
        // standalone. Looking only at helperURL leaves standalone state unread.
        if let helper = targetURL, targetProcesses
            .contains(where: { !$0.isTerminated && $0.bundleURL?.standardizedFileURL == helper.standardizedFileURL }) {
            requestVisibilityRead()
        } else { visibilityCache = nil }
        emitSnapshot()
    }
    func toggle() {
        guard !pending else { return }
        let state = snapshot()
        if let app=standalone,state["visible"] as? Bool != true,state["binding"] as? String != "CONNECTED_READONLY" { connectStandalone(app) }
        setVisible(!(state["visible"] as? Bool == true))
    }
    func connectStandalone(_ app:NSRunningApplication) {
        guard !authorizationPending else{return}
        let alert=NSAlert();alert.messageText="连接夜璃并授权任务控制 / Connect Nyra and authorize task controls"
        alert.informativeText="将当前 TWOS 的左右侧活动关联到已经运行的夜璃。共享状态和简短任务标题；允许你在夜璃中主动追加、编辑未发送指令及停止准确任务。不会自动批准或扩大目录权限。\nConnect this TWOS's two-pane activity to the running Nyra. Share minimal status and short task titles, and enable your explicit append/edit/stop actions for bound tasks. No autonomous execution, approval or expanded workspace access."
        alert.addButton(withTitle:"连接并授权 / Connect and authorize");alert.addButton(withTitle:"仅显示或隐藏 / Visibility only")
        guard alert.runModal() == .alertFirstButtonReturn else{return}
        guard let target=app.bundleURL,let ownID=Bundle.main.bundleIdentifier else{controlFailure="NYRA_CONNECTION_UNAVAILABLE_OR_UPDATE_REQUIRED";refresh();return}
        authorizationGeneration+=1;let generation=authorizationGeneration
        authorizationPending=true;emitSnapshot()
        let root=standaloneStateRoot
        let endpoint=stateRoot.deletingLastPathComponent().appendingPathComponent("nyra-status/endpoint.json").path
        let ownApp=Bundle.main.bundleURL,authorize=authorizeConsumer
        DispatchQueue.global(qos:.userInitiated).async{[weak self] in
            let failure:String?
            do {
                guard !app.isTerminated,(Bundle(url:target)?.object(forInfoDictionaryKey:"NyraVisibilityProtocol") as? Int ?? 0)>=2,
                      let ownHash=Self.signedCodeHash(ownApp) else{throw CocoaError(.fileReadNoPermission)}
                try authorize(app)
                guard !app.isTerminated else{throw CocoaError(.fileReadNoPermission)}
                try NativeWorkbench.safeDirectory(root)
                let selection:[String:Any]=["endpoint":endpoint,"producerApp":ownApp.path,"producerBundleID":ownID,"producerCodeHash":ownHash.base64EncodedString(),"connection_nonce":UUID().uuidString]
                let file=root.appendingPathComponent("bridge-selection.json")
                try JSONSerialization.data(withJSONObject:selection).write(to:file,options:.atomic)
                try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:file.path)
                failure=nil
            } catch {failure="NYRA_CONNECTION_UNAVAILABLE_OR_UPDATE_REQUIRED"}
            DispatchQueue.main.async {
                guard let self=self,self.authorizationGeneration==generation else{return}
                self.authorizationPending=false;self.controlFailure=failure
                if failure==nil,!app.isTerminated {
                    // Hint only: the consumer still authenticates the exact live peer.
                    DistributedNotificationCenter.default().postNotificationName(Notification.Name("com.tianma.nyra.connection.refresh"),object:target.path,userInfo:nil,deliverImmediately:true)
                }
                self.refresh()
                let desired=self.authorizedVisibilityRequest;self.authorizedVisibilityRequest=nil
                if failure==nil,!app.isTerminated,self.standalone?.processIdentifier==app.processIdentifier,let desired=desired {self.setVisible(desired)}
            }
        }
    }

    func setVisible(_ desired: Bool) {
        if authorizationPending {authorizedVisibilityRequest=desired;return}
        guard !pending,let helper = targetURL else { refresh(); return }
        guard standaloneCandidates.isEmpty || standalone != nil else{refresh();return}
        guard !otherEmbeddedHelper else { refresh(); return }
        // Refuse to redirect an already running helper from another installation
        // or profile. A compatible standalone may be shown but is not rebound.
        let running = targetProcesses
        if !isolated {
            let conflicts = NSWorkspace.shared.runningApplications.filter { app in
                !app.isTerminated && ["com.tianma.nyra","local.nyra.companion.preview"].contains(app.bundleIdentifier ?? "") && app.processIdentifier != standalone?.processIdentifier
            }
            if !conflicts.isEmpty {
                changed(["available":false,"reason":"NYRA_VERSION_CONFLICT","binding":"NOT_CONNECTED"]); return
            }
        }
        if running.contains(where: { $0.bundleURL?.standardizedFileURL != helper.standardizedFileURL }) {
            changed(["available": false, "reason": "NYRA_OTHER_INSTALLATION_RUNNING", "binding": "NOT_CONNECTED"]); return
        }
        let state = snapshot()
        if !running.isEmpty && state["observed"] as? Bool != true {
            changed(["available": false, "reason": "NYRA_OTHER_INSTALLATION_RUNNING", "binding": "NOT_CONNECTED"]); return
        }
        if state["observed"] as? Bool == true && state["visible"] as? Bool == desired { refresh(); return }
        controlFailure=nil;pending = true; refresh()
        let options = NSWorkspace.OpenConfiguration(); options.activates = false
        options.allowsRunningApplicationSubstitution = false
        // An isolated candidate must never deliver its visibility URL to an
        // already running Owner helper with the same bundle identifier.
        // Existing exact helpers receive the URL without creating a duplicate.
        options.createsNewApplicationInstance = isolated && running.isEmpty
        if standalone == nil {
            options.environment = ["TWOS_NYRA_STATE_ROOT":stateRoot.path,"NYRA_ISOLATED_ENGINEERING":isolated ? "1" : "0"]
        }
        let url = URL(string: desired ? "twos-nyra://visibility/show" : "twos-nyra://visibility/hide")!
        NSWorkspace.shared.open([url], withApplicationAt: helper, configuration: options) { [weak self] app, error in
            DispatchQueue.main.async {
                guard let self = self else { return }; self.pending = false
                if let error=error as NSError? {self.controlFailure="NYRA_OPEN_FAILED · \(error.domain) \(error.code)"}
                else if app?.bundleURL?.standardizedFileURL != helper.standardizedFileURL {self.controlFailure="NYRA_OPEN_TARGET_MISMATCH"}
                self.refresh()
            }
        }
    }
}

// Separate authenticated user-action channel; status.sock remains pull-only.
final class NyraControlServer {
    final class Connection {
        let fd:Int32; let token=UUID();let lock=NSLock();var live=true
        var source:DispatchSourceRead?
        init(_ fd:Int32){self.fd=fd}
        func invalidate(){lock.lock();live=false;lock.unlock()}
        func valid()->Bool{lock.lock();defer{lock.unlock()};return live}
    }
    let instance:String
    let queue=DispatchQueue(label:"com.tianma.nyra.user-controls",qos:.userInitiated)
    let authenticate:(pid_t,uid_t,String)->Bool
    let handle:([String:Any],@escaping([String:Any])->Void)->Void
    var listener:Int32 = -1
    var source:DispatchSourceRead?
    let path:String
    let focusOnly:Bool
    var clients:[Int32:Connection]=[:]
    var replies:[String:[String:Any]]=[:]
    var pending=Set<String>()
    init(root:URL,instance:String,focusOnly:Bool=false,authenticate:@escaping(pid_t,uid_t,String)->Bool,handle:@escaping([String:Any],@escaping([String:Any])->Void)->Void)throws {
        self.instance=instance;self.authenticate=authenticate;self.handle=handle
        self.focusOnly=focusOnly
        path=root.appendingPathComponent(focusOnly ? "focus.sock":"control.sock").path
        listener=socket(AF_UNIX,SOCK_STREAM,0)
        guard listener>=0 else{throw CocoaError(.fileWriteUnknown)}
        var address=sockaddr_un();address.sun_family=sa_family_t(AF_UNIX);address.sun_len=UInt8(MemoryLayout<sockaddr_un>.size)
        guard path.utf8.count+1<=MemoryLayout.size(ofValue:address.sun_path) else{Darwin.close(listener);throw CocoaError(.fileWriteInvalidFileName)}
        withUnsafeMutableBytes(of:&address.sun_path){b in path.utf8CString.withUnsafeBytes{b.copyMemory(from:$0)}}
        let result=withUnsafePointer(to:&address){$0.withMemoryRebound(to:sockaddr.self,capacity:1){Darwin.bind(listener,$0,socklen_t(MemoryLayout<sockaddr_un>.size))}}
        guard result==0,chmod(path,0o600)==0,listen(listener,4)==0,fcntl(listener,F_SETFL,O_NONBLOCK)==0 else{Darwin.close(listener);throw CocoaError(.fileWriteUnknown)}
        let read=DispatchSource.makeReadSource(fileDescriptor:listener,queue:queue)
        read.setEventHandler{[weak self] in self?.accept()};source=read;read.resume()
    }
    func stop(){source?.cancel();source=nil;queue.async{[self] in for c in Array(clients.values){closeClient(c)};if listener>=0{Darwin.close(listener);listener = -1};unlink(path)}}
    func closeClient(_ c:Connection){guard clients[c.fd] === c else{return};clients.removeValue(forKey:c.fd);c.invalidate();c.source?.cancel();c.source=nil}
    func send(_ value:[String:Any],to c:Connection){
        guard clients[c.fd] === c,let data=try? JSONSerialization.data(withJSONObject:value),data.count<=240_000 else{closeClient(c);return}
        let bytes=data+Data([10]);var offset=0
        func drain(){
            guard self.clients[c.fd] === c else{return}
            let n=bytes.withUnsafeBytes{Darwin.send(c.fd,$0.baseAddress!.advanced(by:offset),bytes.count-offset,MSG_DONTWAIT|MSG_NOSIGNAL)}
            if n>0{offset+=n}
            if offset==bytes.count{self.closeClient(c)}
            else if n<0 && errno != EAGAIN && errno != EWOULDBLOCK{self.closeClient(c)}
            else{self.queue.asyncAfter(deadline:.now()+0.01){drain()}}
        }
        drain()
    }
    func accept(){
        for _ in 0..<4 {
            let fd=Darwin.accept(listener,nil,nil);guard fd>=0 else{return}
            guard clients.count<8 else{Darwin.close(fd);continue}
            var noSignal:Int32=1
            guard fcntl(fd,F_SETFL,O_NONBLOCK)==0,setsockopt(fd,SOL_SOCKET,SO_NOSIGPIPE,&noSignal,socklen_t(MemoryLayout<Int32>.size))==0 else{Darwin.close(fd);continue}
            let c=Connection(fd),read=DispatchSource.makeReadSource(fileDescriptor:fd,queue:queue)
            var bytes=Data(),handled=false
            read.setCancelHandler{Darwin.close(fd)}
            read.setEventHandler{[weak self,weak c] in
                guard let self=self,let c=c,!handled else{return}
                var buffer=[UInt8](repeating:0,count:8192)
                while true {
                    let n=recv(fd,&buffer,buffer.count,0)
                    if n<0 && (errno==EAGAIN || errno==EWOULDBLOCK){return}
                    guard n>0 else{self.closeClient(c);return}
                    bytes.append(contentsOf:buffer.prefix(n))
                    guard bytes.count<=240_000 else{self.closeClient(c);return}
                    if let newline=bytes.firstIndex(of:10){
                        handled=true
                        guard newline==bytes.count-1,let request=(try? JSONSerialization.jsonObject(with:bytes.dropLast())) as? [String:Any] else{self.closeClient(c);return}
                        self.dispatch(request,c:c);return
                    }
                }
            }
            c.source=read;clients[fd]=c;read.resume()
            queue.asyncAfter(deadline:.now()+4){[weak self,weak c] in guard let c=c else{return};self?.closeClient(c)}
        }
    }
    func dispatch(_ request:[String:Any],c:Connection){
        var uid:uid_t=0,gid:gid_t=0,pid:pid_t=0;var size=socklen_t(MemoryLayout<pid_t>.size)
        guard getpeereid(c.fd,&uid,&gid)==0,getsockopt(c.fd,SOL_LOCAL,LOCAL_PEERPID,&pid,&size)==0,
              request["protocol"] as? String==(focusOnly ? "twos.nyra.focus.v1":"twos.nyra.control.v1"),request["hostInstance"] as? String==instance,
              let consumer=request["consumerInstance"] as? String,UUID(uuidString:consumer) != nil,
              let id=request["requestID"] as? String,UUID(uuidString:id) != nil,
              let issued=request["issuedUptime"] as? Double,issued.isFinite,abs(ProcessInfo.processInfo.systemUptime-issued)<4,
              let method=request["method"] as? String,["focus","inspect","draft","submit","editQueue","stop"].contains(method),
              !focusOnly || (method=="focus" && Set(request.keys).isSubset(of:["protocol","hostInstance","consumerInstance","requestID","method","issuedUptime"])),
              authenticate(pid,uid,method) else{send(["requestID":request["requestID"] as? String ?? "","hostInstance":instance,"error":"CONTROL_NOT_AUTHORIZED_OR_STALE"],to:c);return}
        let mutation=["submit","editQueue","stop"].contains(method) || (method=="draft" && request["text"] != nil)
        let key="\(pid)|\(consumer)|\(id)"
        if let response=replies[key]{send(response,to:c);return}
        guard !pending.contains(key) else{send(["requestID":id,"hostInstance":instance,"error":"REQUEST_IN_FLIGHT"],to:c);return}
        guard !mutation || replies.count+pending.count<4096 else{send(["requestID":id,"hostInstance":instance,"error":"CONTROL_RECEIPT_LIMIT_RECONNECT_HOST"],to:c);return}
        if mutation{pending.insert(key)}
        var bound=request;bound["_userControls"] = !focusOnly && authenticate(pid,uid,"submit")
        DispatchQueue.main.async{[weak self,weak c] in
            guard let self=self,let c=c else{return}
            guard c.valid(),abs(ProcessInfo.processInfo.systemUptime-issued)<4 else{
                self.queue.async{self.pending.remove(key);self.closeClient(c)};return
            }
            self.handle(bound){response in
                self.queue.async{
                    if mutation {guard self.pending.remove(key) != nil else{return}}
                    var result=response;result["requestID"]=id;result["hostInstance"]=self.instance
                    if mutation{self.replies[key]=result}
                    self.send(result,to:c)
                }
            }
        }
    }
}

// User actions are bound to one displayed task and reused execution pipelines.
// This metadata endpoint never returns prompts, accounts, paths or attachments.
extension IntegratedWorkbench {
    func nyraTask(_ index:Int)->[String:Any]? {
        guard let activity=paneActivities[index], ["ChatGPT","Claude","DeepSeek","Codex"].contains(kinds[index]) else{return nil}
        let active=["running","queued","waiting_user"].contains(activity.state)
        let previous=nyraTaskRows[index]
        if (!activity.fresh || ["PAGE_UNAVAILABLE","CODEX_CONNECTION_UNAVAILABLE"].contains(activity.reason)),
           var retained=previous,retained["provider"] as? String==kinds[index],retained["session"] as? String==activity.session {
            retained["fresh"]=false;retained["state"]="activity_unknown";retained["reason"]=activity.reason
            retained["canAppend"]=false;retained["canEdit"]=false;retained["canStop"]=false;retained["canSteer"]=false
            return retained
        }
        let previousRun=previous?["run"] as? String
        let hadRun=previous?["session"] as? String==activity.session && previousRun != nil && previousRun != "pending"
        // A provider login/landing page or mere waiting input is not a task.
        // Keep an actual ended run, and an owned Codex chat for draft editing.
        guard activity.task != nil || hadRun ||
            (kinds[index]=="Codex" && codex?.historyReady==true && (codex?.tailTurn != nil || codex?.canControl==true)) else{return nil}
        let title:String?
        var scope="", owned=false, draftOwned=false, stopping=false
        if kinds[index]=="Codex",let client=codex {
            title=client.threadRows.first(where:{$0["id"] as? String==client.threadID})?["name"] as? String
            if let thread=client.threadID,let binding=client.ledger.bindings[thread] {
                scope=String(describing:binding.directory)
                owned=client.connected && !client.uncertain && client.controlledThreads.contains(thread)
                draftOwned=client.connected && !client.uncertain && client.canControl && (!active || owned)
            }
            stopping=client.stopRequested
        } else {
            title=webPanes[index]?.web.title
            owned=activity.fresh && activity.reason != "PAGE_UNAVAILABLE" && !(paneActivityTokens[index] ?? "").isEmpty
            draftOwned=owned
            stopping=nyraStops[index].map{$0.task==activity.task && ProcessInfo.processInfo.systemUptime-$0.at<12} ?? false
        }
        let run=activity.task ?? (previous?["run"] as? String ?? "pending")
        let target=nyraStatus.alias("control|\(index)|\(kinds[index])|\(routeRevision)|\(activity.session)|\(run)|\(scope)")
        let fresh=activity.fresh && activity.state != "activity_unknown"
        let selectionScope=nyraStatus.alias("selection|\(index)|\(kinds[index])|\(routeRevision)|\(activity.session)|\(scope)")
        var value:[String:Any] = ["side":index==0 ? "left":"right","provider":kinds[index],"target":target,"scope":selectionScope,
            "title":Self.companionTitle(title) ?? (activity.state=="waiting_user" ? "等待你的操作 / Waiting for you":"当前任务 / Current task"), "state":activity.state,
            "reason":activity.reason,"fresh":fresh,"canAppend":fresh && active && owned && !stopping,
            "canEdit":fresh && draftOwned && !stopping,
            "canStop":fresh && active && owned && !stopping,
            "canSteer":fresh && activity.state=="running" && owned && kinds[index]=="Codex" && codex?.turnID != nil,
            "session":activity.session,"run":run]
        if stopping {value["state"]="stopping";value["canAppend"]=false;value["canEdit"]=false;value["canStop"]=false}
        if let stop=nyraStops[index],stop.task==activity.task,ProcessInfo.processInfo.systemUptime-stop.at>=12,active {
            value["state"]="stop_unconfirmed";value["reason"]="STOP_TERMINAL_NOT_CONFIRMED"
        }
        return value
    }
    func nyraPublicTasks()->[[String:Any]] {
        (0...1).compactMap {index in
            guard var task=nyraTask(index) else{nyraTaskRows.removeValue(forKey:index);return nil}
            nyraTaskRows[index]=task
            task.removeValue(forKey:"session");task.removeValue(forKey:"run")
            return task
        }
    }
    func handleNyraControl(_ request:[String:Any],reply:@escaping([String:Any])->Void) {
        dispatchPrecondition(condition:.onQueue(.main))
        guard let issued=request["issuedUptime"] as? Double,abs(ProcessInfo.processInfo.systemUptime-issued)<4 else{reply(["error":"STALE_ACTION"]);return}
        let method=request["method"] as? String ?? ""
        if method=="inspect" {
            let session=(0...1).map { paneActivities[$0]?.session ?? "unknown" }.joined(separator:"|")
            let active=(0...1).compactMap { paneActivities[$0]?.task }.joined(separator:"|")
            reply(["tasks":nyraPublicTasks(),"userControls":request["_userControls"] as? Bool==true,
                   "statusSession":nyraStatus.alias(session),"statusTask":active.isEmpty ? "":nyraStatus.alias(active),
                   "language":translate("Back")=="Back" ? "en":"zh"]);return
        }
        var index:Int?
        if let target=request["target"] as? String {
            index=(0...1).first{nyraTask($0)?["target"] as? String==target}
            guard index != nil else{reply(["error":"TASK_CHANGED_DRAFT_RETAINED"]);return}
        }
        if method=="focus" {focusNyraWorkbench(index,reply:reply);return}
        guard request["_userControls"] as? Bool==true else{reply(["error":"CONTROL_NOT_AUTHORIZED"]);return}
        guard let index=index,let task=nyraTask(index) else{reply(["error":"TASK_CHANGED_DRAFT_RETAINED"]);return}
        if kinds[index]=="Codex",let client=codex,(!client.connected || client.uncertain) {reply(["error":"HOST_CONNECTION_STATE_UNCONFIRMED_DRAFT_RETAINED"]);return}
        guard task["fresh"] as? Bool==true else{reply(["error":"TASK_OBSERVATION_STALE_DRAFT_RETAINED"]);return}
        if method=="stop" {stopNyraTask(index,task:task,reply:reply);return}
        guard ["draft","submit","editQueue"].contains(method),let target=task["target"] as? String else{reply(["error":"UNSUPPORTED_CONTROL"]);return}
        let text=request["text"] as? String
        guard text.map({$0.utf8.count<=64_000}) ?? true else{reply(["error":"TEXT_LIMIT_64000_BYTES"]);return}
        if kinds[index]=="Codex",let client=codex,let thread=client.threadID {
            guard client.connected,!client.uncertain else{reply(["error":"HOST_CONNECTION_STATE_UNCONFIRMED_DRAFT_RETAINED"]);return}
            guard task["canEdit"] as? Bool==true,let binding=client.ledger.bindings[thread],client.validBinding(binding) else{reply(["error":"TASK_NOT_CONTROLLED_BY_TWOS"]);return}
            if let queueID=request["queueID"] as? String {
                guard let item=client.ledger.submissions.first(where:{$0.id==queueID && $0.thread==thread && $0.state=="queued"}) else{reply(["error":"INPUT_ALREADY_DISPATCHED"]);return}
                if method=="draft",text==nil {reply(["text":item.text,"revision":NativeCodex.digest(Data(item.text.utf8)),"queueID":queueID]);return}
                guard method=="editQueue",let text=text,request["revision"] as? String==NativeCodex.digest(Data(item.text.utf8)) else{reply(["error":"DRAFT_CHANGED"]);return}
                guard client.editQueue(["id":queueID,"text":text]) else{reply(["error":"QUEUE_EDIT_NOT_SAVED"]);return};reply(["state":"edited","text":text,"revision":NativeCodex.digest(Data(text.utf8))]);return
            }
            let revision=NativeCodex.digest(Data(client.draftText.utf8))
            if method=="draft",text==nil {
                var result:[String:Any] = ["text":client.draftText,"revision":revision,"canSubmit":task["canAppend"] as? Bool==true,"mode":client.ledger.mode=="steer" ? "steer":"queue",
                       "queue":client.ledger.submissions.filter{$0.thread==thread && $0.state=="queued"}.map{["id":$0.id,"label":"Pending input / 待发指令"]}]
                if let receipt=request["receipt"] as? String {
                    guard let record=client.ledger.submissions.first(where:{$0.id==receipt && $0.thread==thread}) else{reply(["error":"RECEIPT_NOT_FOUND"]);return}
                    result["receiptState"]=record.state
                }
                reply(result);return
            }
            guard let text=text,request["revision"] as? String==revision else{reply(["error":"DRAFT_CHANGED"]);return}
            if method=="draft" {guard client.saveDraft(text) else{reply(["error":"DRAFT_NOT_SAVED"]);return};client.emitDraft();reply(["state":"saved","revision":NativeCodex.digest(Data(text.utf8))]);return}
            guard method=="submit",task["canAppend"] as? Bool==true,client.controlledThreads.contains(thread),client.draftAttachments.isEmpty else{reply(["error":"REVIEW_TASK_OR_ATTACHMENTS_IN_TWOS"]);return}
            let mode=request["mode"] as? String ?? "queue"
            guard ["steer","queue"].contains(mode),mode != "steer" || task["canSteer"] as? Bool==true else{reply(["error":"STEER_UNAVAILABLE_NO_RESTART"]);return}
            let current=client.ledger.submissions.first{$0.id==client.activeSubmission}
            guard let item=client.makeSubmission(text:text,model:mode=="steer" ? current?.model ?? client.nextModel:client.nextModel,
                effort:mode=="steer" ? current?.effort ?? client.nextEffort:client.nextEffort,mode:mode),
                mode != "steer" || current?.turn==client.turnID else{reply(["error":"INPUT_NOT_ACCEPTED_REVIEW_TWOS"]);return}
            guard client.acceptSubmission(item) else{reply(["error":"RECEIPT_NOT_SAVED"]);return}
            if mode=="steer" {client.steer(item)} else {client.acknowledge(item)}
            reply(["state":mode=="steer" ? "sending":"queued","receipt":item.id]);return
        }
        guard let pane=webPanes[index],let url=NativeWorkbench.restorableURL(pane.web.url,service:pane.serviceHome) else{reply(["error":"PAGE_UNAVAILABLE"]);return}
        let queueID=request["queueID"] as? String
        let saved=webTransfers.firstIndex{r in r.nyraTarget==target && r.targetPane==index && r.provider==kinds[index] && (queueID.map{$0==r.id} ?? (r.state=="nyra_draft"))}
        if method=="draft",text==nil {
            let body=saved.map{webTransfers[$0].text} ?? ""
            reply(["text":body,"revision":NativeCodex.digest(Data(body.utf8)),"canSubmit":task["canAppend"] as? Bool==true,"mode":"queue",
                "queue":webTransfers.filter{$0.nyraTarget==target && $0.state=="queued" && $0.mayHaveSent != true}.map{["id":$0.id,"label":"Pending input / 待发指令"]}]);return
        }
        guard let text=text,request["revision"] as? String==NativeCodex.digest(Data((saved.map{webTransfers[$0].text} ?? "").utf8)),
              saved.map({webTransfers[$0].mayHaveSent != true && ["nyra_draft","queued"].contains(webTransfers[$0].state)}) ?? (queueID==nil) else{reply(["error":"DRAFT_CHANGED_OR_ALREADY_SENT"]);return}
        guard method=="draft" || (task["canAppend"] as? Bool==true && request["mode"] as? String=="queue" && !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty) else{reply(["error":"WEBSITE_SUPPORTS_SEND_AFTER_COMPLETION_ONLY"]);return}
        var record=WebHandoffReceipt(source:url.absoluteString,message:"nyra-user-"+(request["requestID"] as? String ?? UUID().uuidString),text:text,hash:NativeCodex.digest(Data(text.utf8)),provider:kinds[index],targetPane:index,targetURL:url.absoluteString,binding:routeSignature(1-index))
        record.nyraTarget=target;record.nyraActivity=paneActivityTokens[index];record.files=[];record.state=method=="draft" ? "nyra_draft":"queued"
        if let saved=saved {record.id=webTransfers[saved].id;record.createdAt=webTransfers[saved].createdAt;webTransfers[saved]=record} else{webTransfers.append(record)}
        guard persistWebTransfers() else{reply(["error":"RECEIPT_NOT_SAVED"]);return}
        if record.state=="queued" {observeQueuedTransfer(record.id,target:pane)}
        reply(["state":record.state=="nyra_draft" ? "saved":record.state,"revision":record.hash,"receipt":record.id])
    }
    func focusNyraWorkbench(_ index:Int?,reply:@escaping([String:Any])->Void) {
        guard let window=window else{reply(["error":"WORKBENCH_WINDOW_MISSING"]);return}
        // Restore THIS controller, never resolve an application by display name.
        NSApp.unhide(nil);if window.isMiniaturized {window.deminiaturize(nil)}
        let old=window.collectionBehavior
        if !old.contains(.canJoinAllSpaces) {window.collectionBehavior.insert(.moveToActiveSpace)}
        window.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
        if let index=index {
            if let pane=webPanes[index] {window.makeFirstResponder(pane.web)}
            else if split.arrangedSubviews.indices.contains(index) {window.makeFirstResponder(split.arrangedSubviews[index])}
        }
        let started=ProcessInfo.processInfo.systemUptime
        func observe(){
            let visible=NSApp.isActive && window.isVisible && !window.isMiniaturized && window.isKeyWindow && window.occlusionState.contains(.visible)
            if visible || ProcessInfo.processInfo.systemUptime-started>=0.8 {
                window.collectionBehavior=old
                reply(visible ? ["state":"visible","elapsedMs":Int((ProcessInfo.processInfo.systemUptime-started)*1000)] : ["error":"WINDOW_FOCUS_NOT_CONFIRMED"])
            } else {DispatchQueue.main.asyncAfter(deadline:.now()+0.04){observe()}}
        }
        observe()
    }
    func stopNyraTask(_ index:Int,task:[String:Any],reply:@escaping([String:Any])->Void) {
        guard task["canStop"] as? Bool==true else{reply(["error":"STOP_UNAVAILABLE_OR_PENDING"]);return}
        if kinds[index]=="Codex",let client=codex,let thread=client.threadID,client.controlledThreads.contains(thread) {
            client.interrupt()
            reply(["state":client.stopRequested ? "stopping":"stop_unconfirmed","receipt":nyraStatus.alias(client.turnID ?? thread)]);return
        }
        guard let pane=webPanes[index],let url=NativeWorkbench.restorableURL(pane.web.url,service:pane.serviceHome),let target=task["target"] as? String else{reply(["error":"PAGE_UNAVAILABLE"]);return}
        stopDialogueFromPane(index,source:url)
        // Revoke asynchronous pre-send work even when no automatic relay exists.
        // Already sent requests remain uncertain/sent; this never claims recall.
        pane.web.evaluateJavaScript("window.twosTransferLease = crypto.randomUUID()",in:nil,in:NativeWorkbench.handoffWorld,completionHandler:nil)
        for i in webTransfers.indices where webTransfers[i].targetPane==index && currentTargetMatches(webTransfers[i]) && webTransfers[i].mayHaveSent != true && ["preparing","queued","queue_paused","busy"].contains(webTransfers[i].state) {
            let id=webTransfers[i].id;activeWebQueues.remove(id);transferTimers.removeValue(forKey:id)?.invalidate();webTransfers[i].state="cancelled"
        }
        guard persistWebTransfers() else{reply(["error":"STOP_QUEUE_REVOCATION_NOT_SAVED"]);return}
        nyraStops[index]=(paneActivities[index]?.task,ProcessInfo.processInfo.systemUptime)
        pane.stopFromCompanion(url:url,activity:paneActivityTokens[index] ?? "",stillBound:{[weak self] in self?.nyraTask(index)?["target"] as? String==target}){[weak self] result in
            if result != "stopping" {self?.nyraStops.removeValue(forKey:index)}
            reply(result=="stopping" ? ["state":"stopping"]:["error":result])
        }
    }
}
