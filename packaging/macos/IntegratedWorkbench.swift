import AppKit
import WebKit
import CryptoKit
import Security
import Darwin

// A single, pull-only local snapshot. The endpoint is not a command channel.
// Nyra's consumer is maintained separately; hiding/quitting it never affects work.
final class NyraStatusProducer {
    static let schemaVersion = "twos.nyra.status.v1"
    static let schemaSHA256 = "7ce0d27865647a5ba9bfa44d2355cb3839a80b51348b195fadafc3d7544cc386"
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
    init(directory: URL, helper: URL) {
        self.directory = directory; self.helper = helper
        do {
            try NativeWorkbench.safeDirectory(directory)
            let attrs = try nativePathMetadata(directory.path)
            guard attrs.st_uid == getuid(), attrs.st_mode & 0o777 == 0o700 else { throw CocoaError(.fileWriteNoPermission) }
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
    func observe(session: String, task: String?, state: String, source: String, ownerEvidence: String? = nil) {
        dispatchPrecondition(condition: .onQueue(.main))
        guard Self.validID(session), task.map(Self.validID) ?? true, Self.states.contains(state),
              ["twos_runtime", "codex_adapter", "web_handoff_adapter"].contains(source),
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
           current["evidence_ref"] as? String == effectiveEvidence { return }
        sequence += 1
        current = ["schema_version": Self.schemaVersion, "producer_instance_id": instance,
                   "event_id": UUID().uuidString, "sequence": sequence,
                   "timestamp": ISO8601DateFormatter().string(from: Date()),
                   "session_id": session, "task_id": task as Any? ?? NSNull(),
                   "state": effective, "source": effectiveSource, "simulation": false]
        if effective == "verified_success", let evidence = effectiveEvidence { current["evidence_ref"] = evidence }
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
    func accepts(pid: pid_t, uid: uid_t) -> Bool {
        guard uid == getuid(),
              let app = NSRunningApplication(processIdentifier: pid),
              app.bundleIdentifier == "com.tianma.workos.nyra",
              app.bundleURL?.standardizedFileURL == helper.standardizedFileURL,
              let executable = Bundle(url: helper)?.executableURL,
              app.executableURL?.standardizedFileURL == executable.standardizedFileURL,
              helper.resolvingSymlinksInPath() == helper.standardizedFileURL else { return false }
        // Bind the live peer to the signed helper inside THIS app, not a name,
        // distributed notification or a mutable boolean supplied by a caller.
        var disk: SecStaticCode?; var live: SecCode?
        guard SecStaticCodeCreateWithPath(helper as CFURL, [], &disk) == errSecSuccess,
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
final class IntegratedWorkbench: NSWindowController {
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
    var nyraObservationTimer: Timer?
    var handoffWindow: NSWindow?
    let handoffPicker = NSPopUpButton(frame: .zero, pullsDown: false)
    let handoffDetail = NSTextView()
    let handoffHistoryButton = NSButton(title: "", target: nil, action: nil)
    var historyButtons: [(NSButton, String)] = []
    let nyraButton = NSButton(title: "Nyra", target: nil, action: nil)
    lazy var nyraStatus = NyraStatusProducer(directory: preferences.appendingPathComponent("nyra-status"), helper: Bundle.main.bundleURL.appendingPathComponent("Contents/Helpers/TWOS Nyra.app"))
    lazy var nyra = NativeNyra(stateRoot: preferences.appendingPathComponent("nyra"), producerInstance: { [weak self] in self?.nyraStatus.instance }) { [weak self] state in
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
        for (n, picker) in [leftPicker, rightPicker].enumerated() {
            picker.addItems(withTitles: options.map { translate($0) }); picker.selectItem(at: options.firstIndex(of: kinds[n]) ?? 0)
            picker.tag = n; picker.target = self; picker.action = #selector(changePane(_:))
            picker.setAccessibilityLabel(translate(n == 0 ? "Left service" : "Right service"))
        }
        let title = NSTextField(labelWithString: translate("One workspace · two connected contexts"))
        title.textColor = .secondaryLabelColor; toolbarTitle = title
        let spacer = NSView(); spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        nyraButton.target = self; nyraButton.action = #selector(toggleNyra)
        handoffHistoryButton.title = translate("Handoff history")
        handoffHistoryButton.target = self; handoffHistoryButton.action = #selector(showWebHistory)
        let bar = NSStackView(views: [leftPicker, title, spacer, handoffHistoryButton, nyraButton, rightPicker]); bar.spacing = 18
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
        let statusTimer = Timer(timeInterval: 2, repeats: true) { [weak self] _ in self?.refreshNyraStatus() }
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
    func refreshLanguage() {
        nyra.refresh()
        handoffHistoryButton.title = translate("Handoff history")
        handoffWindow?.title = translate("Handoff history")
        historyButtons.forEach { $0.0.title = translate($0.1) }
        refreshWebHistory()
        toolbarTitle?.stringValue = translate("One workspace · two connected contexts")
        for picker in [leftPicker, rightPicker] {
            for (index, option) in options.enumerated() { picker.item(at: index)?.title = translate(option) }
            picker.setAccessibilityLabel(translate(picker.tag == 0 ? "Left service" : "Right service"))
        }
        webCache.values.forEach { $0.refreshLanguage() }; refreshTargets()
    }
    func start() {
        showWindow(nil); NSApp.activate(ignoringOtherApps: true)
        split.adjustSubviews()
        if split.bounds.width > 0 { split.setPosition(split.bounds.width * 0.52, ofDividerAt: 0) }
    }
    @objc func changePane(_ sender: NSPopUpButton) {
        let index = sender.tag, next = options[sender.indexOfSelectedItem], previous = kinds[index]
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
        }
        view.translatesAutoresizingMaskIntoConstraints = false; host.addSubview(view)
        NSLayoutConstraint.activate([view.leadingAnchor.constraint(equalTo: host.leadingAnchor), view.trailingAnchor.constraint(equalTo: host.trailingAnchor),
                                     view.topAnchor.constraint(equalTo: host.topAnchor), view.bottomAnchor.constraint(equalTo: host.bottomAnchor)])
    }
    func configureHandoff(_ pane: NativeWorkbench, index: Int) {
        pane.inspectHandler = { [weak self, weak pane] id, source in
            guard let self = self, let record = self.webTransfers.first(where: { $0.id == id && $0.source == source.absoluteString }) else { return }
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
            guard let self = self, let pane = pane, self.webPanes[index] === pane,
                  self.kinds[index] == "Claude" else { return }
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
        // Only the right pane selected by the user; no history scanning, prompts,
        // account data, paths, or commands enter the read-only status interface.
        if kinds[1] == "Codex", let client = codex, let thread = client.threadID {
            let run = client.telemetry.runs.values.filter { $0.thread == thread }.max { $0.lastActivity < $1.lastActivity }
            if run?.terminal != false, let queued = client.ledger.submissions.first(where: { $0.thread == thread && $0.turn == nil && ["queued", "preparing", "sending", "accepted", "unknown"].contains($0.state) }) {
                nyraStatus.observe(session: thread, task: queued.id, state: queued.state == "unknown" ? "disconnected" : "queued", source: "codex_adapter")
            } else if let run = run {
                let submission = client.observedSubmission(for: run)
                let state = NyraStatusProducer.codexState(run: run, online: client.connected && !client.uncertain, business: submission?.businessResult)
                if run.state == "completed", let check = submission?.validOwnerResultCheck, check.turn == run.turn {
                    nyraStatus.observe(session:thread,task:run.turn,state:"verified_success",source:"twos_runtime",ownerEvidence:check.id)
                } else { nyraStatus.observe(session: thread, task: run.turn, state: state, source: "codex_adapter") }
            } else { nyraStatus.observe(session: thread, task: nil, state: client.connected ? "idle" : "disconnected", source: "codex_adapter") }
        } else if let pane = webPanes[1], let url = NativeWorkbench.restorableURL(pane.web.url, service: pane.serviceHome) {
            let session = nyraStatus.alias(kinds[1] + "|" + url.absoluteString)
            if let record = webTransfers.last(where: { $0.targetPane == 1 && $0.provider == kinds[1] && ($0.resolvedURL ?? $0.targetURL) == url.absoluteString }) {
                let observation = webRuntimeObservations[record.id]
                let fresh = observation.map { ProcessInfo.processInfo.systemUptime - $0.uptime < 15 } ?? false
                nyraStatus.observe(session: session, task: record.id, state: NyraStatusProducer.webState(record.state, observed: observation?.state, fresh: fresh), source: "web_handoff_adapter")
            } else { nyraStatus.observe(session: session, task: nil, state: "idle", source: "twos_runtime") }
        } else { nyraStatus.observe(session: "unselected", task: nil, state: "idle", source: "twos_runtime") }
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
        refreshNyraStatus()
    }
    @objc func showWebHistory() {
        if handoffWindow == nil {
            let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 520), styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
            w.isReleasedWhenClosed = false; handoffWindow = w
            handoffPicker.target = self; handoffPicker.action = #selector(historySelectionChanged)
            let scroll = NSScrollView(); scroll.hasVerticalScroller = true
            handoffDetail.isEditable = false; handoffDetail.isVerticallyResizable = true; handoffDetail.autoresizingMask = [.width]; scroll.documentView = handoffDetail
            let check = NSButton(title: translate("Check delivery"), target: self, action: #selector(checkHistoryDelivery))
            let resume = NSButton(title: translate("Resume saved handoff…"), target: self, action: #selector(resumeHistoryDelivery))
            let cancel = NSButton(title: translate("Cancel unsent handoff"), target: self, action: #selector(cancelHistoryDelivery))
            historyButtons = [(check, "Check delivery"), (resume, "Resume saved handoff…"), (cancel, "Cancel unsent handoff")]
            let buttons = NSStackView(views: [check, resume, cancel]); buttons.spacing = 10
            let layout = NSStackView(views: [handoffPicker, scroll, buttons]); layout.orientation = .vertical; layout.alignment = .leading; layout.spacing = 12; layout.translatesAutoresizingMaskIntoConstraints = false
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
        historyButtons.forEach { $0.0.isEnabled = false }
        guard let record = selectedWebReceipt else { handoffDetail.string = translate("No website handoffs yet."); return }
        let onTarget = currentTargetMatches(record)
        historyButtons.first?.0.isEnabled = onTarget
        if historyButtons.count == 3 {
            historyButtons[1].0.isEnabled = onTarget && record.mayHaveSent != true && ["draft", "queued", "queue_paused"].contains(record.state)
            historyButtons[2].0.isEnabled = record.mayHaveSent != true && !["cancelled", "sent", "reply", "sending", "unknown"].contains(record.state)
        }
        handoffDetail.string = record.provider + " · " + translate(record.statusLabel) + "\n\n" + record.source + "\n→ " + (record.resolvedURL ?? record.targetURL) + "\n\nID: " + record.id + "\nSHA-256: " + record.hash + "\n\n" + translate("Selected content") + "\n" + record.text + "\n\n" + translate("Website reply") + "\n" + (record.result ?? "—")
    }
    func currentTargetMatches(_ r: WebHandoffReceipt) -> Bool {
        guard kinds[r.targetPane] == r.provider, let pane = webPanes[r.targetPane] else { return false }
        return NativeWorkbench.restorableURL(pane.web.url, service: pane.serviceHome)?.absoluteString == (r.resolvedURL ?? r.targetURL)
    }
    @objc func checkHistoryDelivery() {
        guard let r = selectedWebReceipt, kinds[r.targetPane] == r.provider, let pane = webPanes[r.targetPane] else { return }
        inspectWebTransfer(r.id, target: pane)
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
        if let previous = webTransfers.last(where: { $0.source == source.absoluteString && $0.hash == hash && $0.provider == provider && ($0.mayHaveSent == true || (($0.resolvedURL ?? $0.targetURL) == url.absoluteString && !["cancelled", "target_changed", "rejected", "verification", "login", "not_loaded", "busy", "draft_conflict", "unsupported"].contains($0.state))) }) {
            if ["draft", "queue_paused", "queued"].contains(previous.state), previous.mayHaveSent != true { resumedDraft = previous }
            else {
                publishWebTransfer(previous.id)
                inspectWebTransfer(previous.id, target: target)
                origin.showNotice("This handoff is already recorded. Its delivery is being checked; it will not be sent twice."); return
            }
        }
        guard !webLedgerError else { origin.showNotice("Handoff history is unavailable. Sending is blocked to prevent a duplicate."); return }
        let record = resumedDraft ?? WebHandoffReceipt(source: source.absoluteString, message: message, text: text, hash: hash, provider: provider, targetPane: destination, targetURL: url.absoluteString, binding: binding)
        // The explicit card/toolbar click authorizes this frozen, text-only
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
        webTransfers[i].state = "sending"
        webRuntimeObservations[id] = ("sending", ProcessInfo.processInfo.systemUptime)
        webTransfers[i].mayHaveSent = true // Persist before crossing the website boundary.
        guard persistWebTransfers() else { return }
        publishWebTransfer(id)
        target.webTransfer(record.request(inspectOnly: false)) { [weak self, weak target] response in
            self?.applyWebResponse(id, response: response, dispatchResponse: true)
            if let target = target, ["sent", "unknown"].contains(response["state"] as? String ?? "") { self?.observeWebTransfer(id, target: target) }
        }
    }
    func applyWebResponse(_ id: String, response: [String: Any], dispatchResponse: Bool = false) {
        guard let i = webTransfers.firstIndex(where: { $0.id == id }) else { return }
        let allowed = ["sent", "reply", "unknown", "draft", "verification", "login", "busy", "not_loaded", "target_changed", "unsupported", "draft_conflict"]
        var state = response["state"] as? String ?? "unknown"
        guard allowed.contains(state) else { return }
        // Activity evidence is separate from the irreversible delivery receipt.
        // A failed read must invalidate animation liveness without erasing SENT.
        if webRuntimeObservations.count > 128 { webRuntimeObservations.removeAll() }
        webRuntimeObservations[id] = (state, ProcessInfo.processInfo.systemUptime)
        // Only the original call can prove a pre-send refusal. Read-only polling
        // after SPA navigation must never turn uncertain delivery into "not sent".
        if !dispatchResponse && !["sent", "reply"].contains(state) { state = "unknown" }
        if dispatchResponse && !["sent", "reply", "unknown"].contains(state) { webTransfers[i].mayHaveSent = false }
        if ["sent", "reply"].contains(state) { webTransfers[i].mayHaveSent = true }
        if dispatchResponse && state == "busy" { state = "queued" }
        // A later inspection failure cannot erase an established send receipt.
        if webTransfers[i].state != "reply" && (webTransfers[i].state != "sent" || state == "reply") { webTransfers[i].state = state }
        if let destination = response["conversationURL"] as? String, let original = URL(string: webTransfers[i].targetURL),
           let actual = NativeWorkbench.restorableURL(URL(string: destination), service: original) { webTransfers[i].resolvedURL = actual.absoluteString }
        if let reply = response["reply"] as? String, state == "reply", reply.utf8.count <= 200_000 { webTransfers[i].result = reply }
        webTransfers[i].updatedAt = Date().timeIntervalSince1970
        if persistWebTransfers() { publishWebTransfer(id) }
        if state == "queued", let target = webPanes[webTransfers[i].targetPane] { observeQueuedTransfer(id, target: target) }
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
        guard let record = webTransfers.first(where: { $0.id == id }) else { return }
        target.webTransfer(record.request(inspectOnly: true)) { [weak self] value in self?.applyWebResponse(id, response: value) }
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
    var resolvedURL: String?
    var resumeDraft: Bool?
    var mayHaveSent: Bool?
    var state = "preparing"
    var result: String?
    var createdAt = Date().timeIntervalSince1970
    var updatedAt = Date().timeIntervalSince1970
    var statusLabel: String {
        switch state {
        case "reply": return "Reply received. No local file was created."
        case "sent": return "The website contains this exact instruction."
        case "draft": return "Draft only. Review and send it in the website."
        case "verification": return "Complete the website's human verification. Nothing was sent."
        case "login": return "Sign in to this website. Nothing was sent."
        case "busy": return "The target is replying. This handoff is saved and has not been sent."
        case "queued": return "Queued for this exact website conversation. Switches or login changes pause dispatch."
        case "queue_paused": return "Queue paused. Open the original conversation and explicitly resume from Handoff history."
        case "cancelled": return "Unsent handoff cancelled. Existing website drafts are preserved."
        case "target_changed": return "The destination changed. Nothing was sent."
        case "draft_conflict": return "The target has an existing draft. It has been preserved."
        case "unsupported": return "No verified website send control is available. Nothing was sent."
        case "sending": return "Sending the confirmed instruction."
        default: return "Delivery needs verification. It will not be repeated automatically."
        }
    }
    func request(inspectOnly: Bool) -> [String: Any] {
        ["id": id, "text": text, "hash": hash, "provider": provider, "targetURL": resolvedURL ?? targetURL, "inspectOnly": inspectOnly, "draftOnly": false, "resumeDraft": resumeDraft == true]
    }
    var card: [String: Any] {
        ["id": id, "source": source, "message": message, "hash": hash, "provider": provider, "targetURL": resolvedURL ?? targetURL, "state": state, "createdAt": createdAt, "retryable": mayHaveSent != true && ["draft", "login", "verification", "busy", "not_loaded", "draft_conflict", "unsupported", "target_changed"].contains(state), "inspectable": mayHaveSent == true || state == "unknown", "result": result ?? "", "error": statusLabel, "attachments": []]
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
              let bundle = Bundle(url:url), bundle.object(forInfoDictionaryKey:"NyraVisibilityProtocol") as? Int == 1 else { return false }
        var code: SecStaticCode?; var requirement: SecRequirement?
        guard SecStaticCodeCreateWithPath(url as CFURL,[],&code) == errSecSuccess,
              SecRequirementCreateWithString("anchor apple generic and certificate leaf[subject.OU] = BZJWQJ352K" as CFString,[],&requirement) == errSecSuccess,
              let code = code, let requirement = requirement else { return false }
        return SecStaticCodeCheckValidity(code,SecCSFlags(rawValue:kSecCSStrictValidate),requirement) == errSecSuccess
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
    let changed: ([String: Any]) -> Void
    var observer: NSObjectProtocol?
    var lifecycleObserver: NSObjectProtocol?
    var pending = false
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
    init(stateRoot: URL, producerInstance: @escaping () -> String? = { nil }, changed: @escaping ([String: Any]) -> Void) {
        self.stateRoot = stateRoot; self.producerInstance = producerInstance; self.changed = changed; super.init()
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
        if let helper = helperURL, targetProcesses
            .contains(where: { !$0.isTerminated && $0.bundleURL?.standardizedFileURL == helper.standardizedFileURL }) {
            requestVisibilityRead()
        } else { visibilityCache = nil }
        emitSnapshot()
    }
    func toggle() {
        guard !pending else { return }
        let state = snapshot()
        setVisible(!(state["visible"] as? Bool == true))
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
        pending = true; refresh()
        let options = NSWorkspace.OpenConfiguration(); options.activates = false
        if standalone == nil {
            options.environment = ["TWOS_NYRA_STATE_ROOT":stateRoot.path,"NYRA_ISOLATED_ENGINEERING":isolated ? "1" : "0"]
        }
        let url = URL(string: desired ? "twos-nyra://visibility/show" : "twos-nyra://visibility/hide")!
        NSWorkspace.shared.open([url], withApplicationAt: helper, configuration: options) { [weak self] _, error in
            DispatchQueue.main.async {
                guard let self = self else { return }; self.pending = false
                if error != nil { self.changed(["available": true, "observed": false, "reason": "NYRA_OPEN_FAILED", "binding": "NOT_CONNECTED"]) }
                else { self.refresh() }
            }
        }
    }
}
