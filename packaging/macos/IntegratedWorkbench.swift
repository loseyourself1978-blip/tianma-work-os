import AppKit
import WebKit
import CryptoKit
import Security
import Darwin

// A single, pull-only local snapshot. The endpoint is not a command channel.
// Nyra's consumer is maintained separately; hiding/quitting it never affects work.
final class NyraStatusProducer {
    static let schemaVersion = "twos.nyra.status.v2"
    static let schemaSHA256 = "ef6797aa662f28dd36134ba476c5b1ae50c418fd1fa9636330d2cb76c0b59c81"
    static let states: Set<String> = ["idle", "queued", "running", "waiting_user", "partial", "failed", "completed_unverified", "verified_success", "cancelled", "disconnected"]
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
    init(directory: URL, helper: URL) {
        self.directory = directory; self.helper = helper
        do {
            try NativeWorkbench.safeDirectory(directory)
            let attrs = try nativePathMetadata(directory.path)
            guard attrs.st_uid == getuid(), attrs.st_mode & 0o777 == 0o700 else { throw CocoaError(.fileWriteNoPermission) }
            if let saved=NativeNyra.readVisibility(directory.appendingPathComponent("authorized-consumer.json")),
               let path=saved["path"] as? String,let encoded=saved["hash"] as? String,let hash=Data(base64Encoded:encoded) {authorizedStandalone=(path,hash)}
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
            let bytes = try JSONSerialization.data(withJSONObject: ["transport":"unix_snapshot_v1", "socket":path, "producer_instance_id":instance, "schema_version":Self.schemaVersion, "schema_sha256":Self.schemaSHA256])
            try bytes.write(to: file, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
            let source = DispatchSource.makeReadSource(fileDescriptor: socketFD, queue: socketQueue)
            source.setEventHandler { [weak self] in self?.acceptSnapshots() }
            socketSource = source; source.resume()
        } catch { endpointError = "LOCAL_STATUS_ENDPOINT_UNAVAILABLE" }
        observe(session: "unselected", task: nil, state: "idle", source: "twos_runtime")
    }
    deinit {
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
    func observe(session: String, task: String?, state: String, source: String, ownerEvidence: String? = nil, side: String? = nil) {
        dispatchPrecondition(condition: .onQueue(.main))
        guard Self.validID(session), task.map(Self.validID) ?? true, Self.states.contains(state),
              ["twos_runtime", "codex_adapter", "web_handoff_adapter"].contains(source),
              side.map({["left","right","both"].contains($0)}) ?? true,
              state != "verified_success" || (source == "twos_runtime" && task != nil && ownerEvidence.map(Self.validID) == true) else { return }
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
           current["evidence_ref"] as? String == effectiveEvidence, current["activity_side"] as? String == side { return }
        sequence += 1
        current = ["schema_version": side == nil ? "twos.nyra.status.v1" : Self.schemaVersion, "producer_instance_id": instance,
                   "event_id": UUID().uuidString, "sequence": sequence,
                   "timestamp": ISO8601DateFormatter().string(from: Date()),
                   "session_id": session, "task_id": task as Any? ?? NSNull(),
                   "state": effective, "source": effectiveSource, "simulation": false]
        if effective == "verified_success", let evidence = effectiveEvidence { current["evidence_ref"] = evidence }
        if let side=side { current["activity_side"]=side }
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
        case "cancelled": return "cancelled"
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
        try JSONSerialization.data(withJSONObject:["path":url.path,"hash":hash.base64EncodedString()]).write(to:file,options:.atomic)
        try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:file.path)
        snapshotLock.lock();authorizedStandalone=(url.path,hash);snapshotLock.unlock()
    }
    func accepts(pid: pid_t, uid: uid_t) -> Bool {
        snapshotLock.lock();let approved=authorizedStandalone;snapshotLock.unlock()
        guard uid==getuid(),let app=NSRunningApplication(processIdentifier:pid),let path=app.bundleURL else{return false}
        let isEmbedded=app.bundleIdentifier=="com.tianma.workos.nyra" && path.standardizedFileURL==helper.standardizedFileURL
        let isStandalone=app.bundleIdentifier==NativeNyra.standaloneID && approved?.path==path.path && NativeNyra.compatibleStandalone(app) && approved?.hash==NativeNyra.signedCodeHash(path)
        guard isEmbedded || isStandalone else{return false}
        let selected=isEmbedded ? helper : path
        guard uid == getuid(),
              app.bundleURL?.standardizedFileURL == selected.standardizedFileURL,
              let executable = Bundle(url: selected)?.executableURL,
              app.executableURL?.standardizedFileURL == executable.standardizedFileURL,
              selected.resolvingSymlinksInPath() == selected.standardizedFileURL else { return false }
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
        return actual == expected
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

// A single app/window owns both panes. No foreign window positioning, capture,
// screen mirror, remote-control service, or keyboard synthesis is involved.
final class IntegratedWorkbench: NSWindowController, NSWindowDelegate {
    let preferences: URL
    let resources: URL?
    let translate: (String) -> String
    let openProjects: () -> Void
    var languageChanged: ((String) -> Bool)?
    var toolbarTitle: NSTextField?
    let split = NSSplitView()
    let leftPicker = NSPopUpButton(frame: .zero, pullsDown: false)
    let rightPicker = NSPopUpButton(frame: .zero, pullsDown: false)
    var webPanes: [Int: NativeWorkbench] = [:]
    var webCache: [String: NativeWorkbench] = [:]
    var codex: NativeCodex?
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
    let nyraConnectionButton = NSButton(title:"Nyra status",target:nil,action:nil)
    lazy var nyraStatus = NyraStatusProducer(directory: preferences.appendingPathComponent("nyra-status"), helper: Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/TWOS Nyra.app"))
    lazy var nyra = NativeNyra(stateRoot: preferences.appendingPathComponent("nyra"), producerInstance: { [weak self] in self?.nyraStatus.instance }, authorizeConsumer:{ [weak self] app in
        guard let self=self else{throw CocoaError(.fileReadUnknown)}
        try self.nyraStatus.authorizeStandalone(app)
    }) { [weak self] state in
        guard let self = self else { return }
        let visible = state["visible"] as? Bool == true
        self.nyraButton.title = self.translate(state["available"] as? Bool == false ? "Nyra · view status" : (visible ? "Hide Nyra" : "Show Nyra"))
        self.nyraButton.isEnabled = state["pending"] as? Bool != true
        self.nyraButton.toolTip = state["reason"] as? String
        self.nyraButton.setAccessibilityLabel(self.nyraButton.title)
        self.codex?.emit("nyra", state)
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
                if dialogue?.state == "running" { dialogue?.state="paused";dialogue?.reason="App restarted. Reconcile the pending receipt before continuing." }
            } catch { dialogue=nil;webLedgerError=true }
        }
        for (n, picker) in [leftPicker, rightPicker].enumerated() {
            picker.addItems(withTitles: options.map { translate($0) }); picker.selectItem(at: options.firstIndex(of: kinds[n]) ?? 0)
            picker.tag = n; picker.target = self; picker.action = #selector(changePane(_:))
            picker.setAccessibilityLabel(translate(n == 0 ? "Left service" : "Right service"))
        }
        let title = NSTextField(labelWithString: translate("One workspace · two connected contexts"))
        title.textColor = .secondaryLabelColor; toolbarTitle = title
        let spacer = NSView(); spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        nyraButton.target = self; nyraButton.action = #selector(toggleNyra)
        nyraConnectionButton.target=self;nyraConnectionButton.action=#selector(connectNyra);nyraConnectionButton.title=translate("Nyra status")
        handoffHistoryButton.title = translate("Handoff history")
        handoffHistoryButton.target = self; handoffHistoryButton.action = #selector(showWebHistory)
        dialogueButton.title=translate("Automatic exchange");dialogueButton.target=self;dialogueButton.action=#selector(showDialogue)
        let bar = NSStackView(views: [leftPicker, title, spacer, handoffHistoryButton, dialogueButton, nyraConnectionButton, nyraButton, rightPicker]); bar.spacing = 10
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
        rebuild(0); rebuild(1); refreshTargets(); nyra.refresh(); win.center()
        let statusTimer = Timer(timeInterval: 2, repeats: true) { [weak self] _ in self?.refreshNyraStatus();self?.tickDialogue() }
        nyraObservationTimer = statusTimer; RunLoop.main.add(statusTimer, forMode: .common)
    }
    deinit { nyraObservationTimer?.invalidate() }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    static func validWebsite(_ raw: String) -> URL? {
        guard let url = URL(string: raw), let host = url.host, !host.isEmpty, url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil else { return nil }
        if url.scheme == "https" { return url }
        if url.scheme == "http" && ["localhost", "127.0.0.1", "[::1]"].contains(host) { return url }
        return nil
    }
    @objc func toggleNyra() { _ = nyraStatus; nyra.toggle() }
    @objc func connectNyra() {
        _ = nyraStatus
        if let app=nyra.standalone {nyra.connectStandalone(app)}
        else {
            nyra.refresh();let state=nyra.snapshot(),alert=NSAlert();alert.messageText=translate("Nyra status")
            alert.informativeText=(state["binding"] as? String ?? "NOT_CONNECTED")+"\n"+translate("The bundled Nyra connects to this exact TWOS automatically when shown. No chat or files are shared.")
            if let reason=state["reason"] as? String {
                let parts=reason.components(separatedBy:" · ")
                alert.informativeText += "\n"+translate(parts[0])+(parts.count>1 ? " · "+parts.dropFirst().joined(separator:" · ") : "")
            }
            alert.runModal()
        }
    }
    func refreshLanguage() {
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
              closing === handoffWindow || closing === dialogueWindow else { return }
        // Closing an auxiliary view returns to this workbench, not another
        // installed TWOS instance. It never navigates, resumes, or dispatches.
        DispatchQueue.main.async { [weak self] in
            guard let main = self?.window, main.isVisible, NSApp.isActive else { return }
            main.makeKeyAndOrderFront(nil)
        }
    }
    @objc func changePane(_ sender: NSPopUpButton) {
        let index = sender.tag, next = options[sender.indexOfSelectedItem], previous = kinds[index]
        pauseDialogue("Participant selection changed")
        if previous == "Codex", codex?.isBusy == true { sender.selectItem(at: options.firstIndex(of: previous)!); return }
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
        if next == "Website…" {
            let alert = NSAlert(); alert.messageText = translate("Open a website in this pane")
            alert.informativeText = translate("Enter an HTTPS address, or a local dashboard address. Nothing is sent to the other pane automatically.")
            let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 440, height: 28)); field.placeholderString = "https://…"; alert.accessoryView = field
            alert.addButton(withTitle: translate("Open")); alert.addButton(withTitle: translate("Cancel"))
            guard alert.runModal() == .alertFirstButtonReturn, let url = Self.validWebsite(field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)) else {
                sender.selectItem(at: options.firstIndex(of: previous) ?? 0); return
            }
            urls[index] = url.absoluteString
        } else if let url = defaults[next] { urls[index] = url }
        for pane in webCache.values {
            pane.web.evaluateJavaScript("window.twosTransferLease = Math.random().toString()", in: nil, in: NativeWorkbench.handoffWorld, completionHandler: nil)
        }
        for i in webTransfers.indices where webTransfers[i].state == "queued" {
            activeWebQueues.remove(webTransfers[i].id); transferTimers[webTransfers[i].id]?.invalidate(); webTransfers[i].state = "queue_paused"
        }
        _ = persistWebTransfers()
        kinds[index] = next
        routeRevision = UUID().uuidString
        rebuild(0); rebuild(1); refreshTargets(); save()
    }
    func save() {
        try? NativeWorkbench.save(["kind0": kinds[0], "kind1": kinds[1], "url0": urls[0], "url1": urls[1]], at: preferences.appendingPathComponent("paired-workbench.json"))
    }
    func rebuild(_ index: Int) {
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
            pane.start(embedded: true)
            updateWebFileLabel(index)
        }
        view.translatesAutoresizingMaskIntoConstraints = false; host.addSubview(view)
        NSLayoutConstraint.activate([view.leadingAnchor.constraint(equalTo: host.leadingAnchor), view.trailingAnchor.constraint(equalTo: host.trailingAnchor),
                                     view.topAnchor.constraint(equalTo: host.topAnchor), view.bottomAnchor.constraint(equalTo: host.bottomAnchor)])
    }
    func configureHandoff(_ pane: NativeWorkbench, index: Int) {
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
        let now=ProcessInfo.processInfo.systemUptime
        for index in 0...1 {
            if kinds[index] == "Codex", let client=codex, let thread=client.threadID {
                let run=client.telemetry.runs.values.filter { $0.thread==thread }.max { $0.lastActivity<$1.lastActivity }
                var state=client.connected && !client.uncertain ? "idle" : "disconnected"
                var evidence:String?
                if let run=run { state=NyraStatusProducer.codexState(run:run,online:client.connected && !client.uncertain,business:client.observedSubmission(for:run)?.businessResult) }
                if let run=run,run.state=="completed",client.connected && !client.uncertain,
                   let check=client.observedSubmission(for:run)?.validOwnerResultCheck {
                    state="verified_success";evidence=nyraStatus.alias(check.id)
                }
                if run?.terminal != false, client.ledger.submissions.contains(where:{$0.thread==thread && $0.turn==nil && ["queued","preparing","sending","accepted"].contains($0.state)}) { state="queued" }
                paneActivities[index]=PaneActivity(session:nyraStatus.alias(thread),task:run?.turn,state:state,at:now,evidence:evidence)
            } else if let pane=webPanes[index], kinds[index] != "Codex", let source=NativeWorkbench.restorableURL(pane.web.url,service:pane.serviceHome) {
                let session=nyraStatus.alias(kinds[index]+"|"+source.absoluteString)
                if paneActivities[index]?.session != session { paneActivities[index]=PaneActivity(session:session,task:nil,state:"disconnected",at:now) }
                guard !paneObservationPending.contains(index) else {continue}
                paneObservationPending.insert(index)
                pane.providerSnapshot { [weak self,weak pane] value in
                    guard let self=self else{return};self.paneObservationPending.remove(index)
                    guard let pane=pane,self.webPanes[index] === pane,self.kinds[index] != "Codex",NativeWorkbench.restorableURL(pane.web.url,service:pane.serviceHome)==source else{return}
                    let observed=value["state"] as? String ?? "unknown"
                    pane.reconcileAccessNotice(observed)
                    let state=["idle","running","waiting_user"].contains(observed) ? observed : "disconnected"
                    if state=="running",self.paneActivities[index]?.state != "running" { self.paneActivityRunIDs[index]=UUID().uuidString }
                    if state=="idle" {self.paneActivityRunIDs.removeValue(forKey:index)}
                    self.paneActivities[index]=PaneActivity(session:session,task:self.paneActivityRunIDs[index],state:state,at:ProcessInfo.processInfo.systemUptime)
                    self.publishPaneActivity()
                }
            } else { paneActivities[index]=PaneActivity(session:"unselected",task:nil,state:"disconnected",at:now) }
        }
        publishPaneActivity()
    }
    func publishPaneActivity() {
        var aggregate=PaneActivity.aggregate(paneActivities)
        // Between confirmed replies and the next dispatch this is scheduling,
        // not inference. Read-only inspection alone never creates activity.
        if aggregate.state=="idle",dialogue?.state=="running" {aggregate=("queued","both")}
        let identity=(0...1).map { paneActivities[$0]?.session ?? "unknown" }.joined(separator:"|")
        let active=(0...1).compactMap { paneActivities[$0]?.task }.joined(separator:"|")
        let checks=(0...1).compactMap { paneActivities[$0]?.fresh == true ? paneActivities[$0]?.evidence : nil }.joined(separator:"|")
        nyraStatus.observe(session:nyraStatus.alias(identity),task:active.isEmpty ? nil : nyraStatus.alias(active),state:aggregate.state,source:"twos_runtime",ownerEvidence:aggregate.state=="verified_success" && !checks.isEmpty ? nyraStatus.alias(checks) : nil,side:aggregate.side)
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
              ["unknown","sending","sent"].contains(r.state), kinds[r.targetPane] == r.provider,
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
        if let previous = webTransfers.last(where: { $0.source == source.absoluteString && ($0.files ?? []) == (webFileSelections[index] ?? []) && $0.message == message && $0.hash == hash && $0.provider == provider && $0.targetPane == destination && ($0.resolvedURL ?? $0.targetURL) == url.absoluteString && ($0.mayHaveSent == true || !["cancelled", "target_changed", "rejected", "verification", "login", "not_loaded", "busy", "draft_conflict", "unsupported"].contains($0.state)) }) {
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
        guard kinds[record.targetPane] == record.provider, webPanes[record.targetPane] === target,
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
        let allowed = ["sent", "reply", "unknown", "draft", "verification", "login", "busy", "not_loaded", "target_changed", "unsupported", "draft_conflict", "provider_limited"]
        var state = response["state"] as? String ?? "unknown"
        if let reason=response["reason"] as? String {webTransfers[i].inspection=reason}
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
        if !dispatchResponse && !["sent", "reply"].contains(state) {
            // A read does not send. Preserve an original, explicit pre-send
            // refusal; otherwise a harmless Check would disable its draft
            // recovery/cancel actions. An uncertain dispatch remains unknown.
            let prior = webTransfers[i]
            state = prior.mayHaveSent == false && !["sending", "sent", "reply", "unknown"].contains(prior.state) ? prior.state : "unknown"
        }
        if dispatchResponse && !["sent", "reply", "unknown"].contains(state) { webTransfers[i].mayHaveSent = false }
        if ["sent", "reply"].contains(state) { webTransfers[i].mayHaveSent = true }
        if dispatchResponse && state == "busy" { state = "queued" }
        // A later inspection failure cannot erase an established send receipt.
        if webTransfers[i].state != "reply" && (webTransfers[i].state != "sent" || state == "reply") { webTransfers[i].state = state }
        if ["sent","reply"].contains(state), let destination = response["conversationURL"] as? String, let original = URL(string: webTransfers[i].targetURL),
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
            guard reads <= 100, self.kinds[record.targetPane] == record.provider, self.webPanes[record.targetPane] === target,
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
                  let record = self.webTransfers.first(where: { $0.id == id }), record.state != "reply",
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
    var files: [WebTransferFile]?
    var resolvedURL: String?
    var resumeDraft: Bool?
    var mayHaveSent: Bool?
    var state = "preparing"
    var result: String?
    var resultHash: String?
    var replyMessage: String?
    var inspection: String?
    var inspectedAt: TimeInterval?
    var createdAt = Date().timeIntervalSince1970
    var updatedAt = Date().timeIntervalSince1970
    var statusLabel: String {
        switch state {
        case "reply": return "Reply received. No local file was created."
        case "sent": return "The website contains this exact instruction."
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
            if inspection?.hasPrefix("EXACT_FILE_UPLOAD_CONTROL_UNAVAILABLE") == true {return "The website attachment control is unavailable or ambiguous. Your draft is preserved; nothing was sent."}
            return "No verified website send control is available. Nothing was sent."
        case "sending": return "Sending the confirmed instruction."
        default: return "Delivery needs verification. It will not be repeated automatically."
        }
    }
    func request(inspectOnly: Bool) -> [String: Any] {
        var value: [String: Any] = ["id": id, "text": text, "hash": hash, "provider": provider, "targetURL": resolvedURL ?? targetURL, "inspectOnly": inspectOnly, "draftOnly": false, "resumeDraft": resumeDraft == true]
        // Reconciliation needs the original attachment identity to distinguish
        // website-added file captions from the exact submitted body. Metadata
        // only: observing delivery never rereads or uploads file bytes.
        if inspectOnly {
            value["files"] = (files ?? []).map { ["id":$0.id,"name":$0.name,"mime":$0.mime,"size":$0.size,"hash":$0.hash] as [String:Any] }
        }
        return value
    }
    var card: [String: Any] {
        ["id": id, "source": source, "message": message, "hash": hash, "provider": provider, "targetURL": resolvedURL ?? targetURL, "state": state, "createdAt": createdAt, "retryable": mayHaveSent != true && ["draft", "login", "verification", "busy", "not_loaded", "draft_conflict", "unsupported", "target_changed"].contains(state), "inspectable": mayHaveSent == true || state == "unknown", "result": result ?? "", "error": statusLabel, "inspection": inspection ?? "", "attachments": (files ?? []).map { ["id":$0.id,"name":$0.name,"mime":$0.mime,"size":$0.size,"sha256":$0.hash] as [String:Any] }]
    }
}

// Visibility control uses the pinned helper, or an already-running compatible
// signed standalone Nyra. A standalone display is not claimed as a task binding.
final class NativeNyra: NSObject {
    let stateRoot: URL
    var isolated: Bool { CommandLine.arguments.contains("--diagnostic-root") }
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
    var standalone: NSRunningApplication? {
        guard !isolated else { return nil }
        return NSRunningApplication.runningApplications(withBundleIdentifier:Self.standaloneID).first { !$0.isTerminated && Self.compatibleStandalone($0) }
    }
    var targetURL: URL? { standalone?.bundleURL ?? helperURL }
    var targetStateRoot: URL {
        standalone != nil ? FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("Nyra") : stateRoot
    }
    var targetProcesses: [NSRunningApplication] {
        if let app = standalone { return [app] }
        return NSRunningApplication.runningApplications(withBundleIdentifier:"com.tianma.workos.nyra").filter {
            !$0.isTerminated && (!isolated || $0.bundleURL?.standardizedFileURL == helperURL?.standardizedFileURL)
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
        state["pending"] = pending || stateReadInFlight || state["pending"] as? Bool == true
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
        if let error=controlFailure {state["reason"]=error}
        return state
    }
    private func observedSnapshot() -> [String: Any] {
        guard let helper = targetURL else { return ["available": false, "visible": false, "reason": "NYRA_HELPER_NOT_BUNDLED", "binding": "NOT_CONNECTED"] }
        // No helper means there is no live visibility evidence to read. Besides
        // rejecting old state from another build, this avoids an unnecessary
        // Downloads/TCC file prompt on workbench startup in engineering profiles.
        guard targetProcesses
            .contains(where: { !$0.isTerminated && $0.bundleURL?.standardizedFileURL == helper.standardizedFileURL }) else {
            return ["available": true, "visible": false, "observed": false, "binding": "NOT_CONNECTED"]
        }
        guard let state = visibilityCache, let pid = state["pid"] as? Int32,
              let process = NSRunningApplication(processIdentifier: pid), !process.isTerminated,
              process.bundleURL?.standardizedFileURL == helper.standardizedFileURL,
              state["bundle"] as? String == helper.path else { return ["available": true, "visible": false, "observed": false, "binding": "NOT_CONNECTED"] }
        let connected = state["runBinding"] as? String == "CONNECTED_READONLY" && producerInstance() != nil && state["producerInstance"] as? String == producerInstance()
        return ["available": true, "visible": state["visible"] as? Bool ?? false, "pending": state["pending"] as? Bool ?? false,
                "observed": true, "binding": connected ? "CONNECTED_READONLY" : "NOT_CONNECTED", "updatedAt": state["updatedAt"] ?? NSNull()]
    }
    func refresh() {
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
        let alert=NSAlert();alert.messageText="连接夜璃只读状态 / Connect Nyra read-only status"
        alert.informativeText="将当前 TWOS 的左右侧活动关联到已经运行的夜璃。只共享状态和不透明标识，不共享聊天、文件或账户，也不授予执行或批准权限。\nConnect this TWOS's two-pane activity to the running Nyra. Only minimal state and opaque IDs are shared. No chat, files, account data, execution or approval rights."
        alert.addButton(withTitle:"连接 / Connect");alert.addButton(withTitle:"仅显示或隐藏 / Visibility only")
        guard alert.runModal() == .alertFirstButtonReturn else{return}
        do {
            guard let target=app.bundleURL,(Bundle(url:target)?.object(forInfoDictionaryKey:"NyraVisibilityProtocol") as? Int ?? 0)>=2,
                  let ownHash=Self.signedCodeHash(Bundle.main.bundleURL),let ownID=Bundle.main.bundleIdentifier else{throw CocoaError(.fileReadNoPermission)}
            try authorizeConsumer(app)
            let root=targetStateRoot;try NativeWorkbench.safeDirectory(root)
            let selection:[String:Any]=["endpoint":stateRoot.deletingLastPathComponent().appendingPathComponent("nyra-status/endpoint.json").path,"producerApp":Bundle.main.bundleURL.path,"producerBundleID":ownID,"producerCodeHash":ownHash.base64EncodedString(),"connection_nonce":UUID().uuidString]
            let file=root.appendingPathComponent("bridge-selection.json")
            try JSONSerialization.data(withJSONObject:selection).write(to:file,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:file.path)
            // Notification is a refresh hint only. Nyra still validates both
            // file permissions and the live signed socket peer before trusting it.
            DistributedNotificationCenter.default().postNotificationName(Notification.Name("com.tianma.nyra.connection.refresh"),object:target.path,userInfo:nil,deliverImmediately:true)
            controlFailure=nil
            refresh()
        } catch {controlFailure="NYRA_CONNECTION_UNAVAILABLE_OR_UPDATE_REQUIRED";refresh()}
    }
    func setVisible(_ desired: Bool) {
        guard !pending, let helper = targetURL else { refresh(); return }
        // Refuse to redirect an already running helper from another installation
        // or profile. A compatible standalone may be shown but is not rebound.
        let running = targetProcesses
        if !isolated {
            let conflicts = NSWorkspace.shared.runningApplications.filter { app in
                !app.isTerminated && ["com.tianma.nyra","local.nyra.companion.preview"].contains(app.bundleIdentifier ?? "") && !Self.compatibleStandalone(app)
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
