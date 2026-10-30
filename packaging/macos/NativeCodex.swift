import AppKit
import WebKit
import Darwin
import CryptoKit
import UniformTypeIdentifiers

// These records belong to TWOS, not to Codex's internal database. A durable
// intent is saved before every mutation; ambiguous delivery is never replayed.
struct CodexDirectory: Codable, Equatable {
    let path: String
    let device: UInt64
    let inode: UInt64
    let isolated: Bool
}
struct CodexBinding: Codable {
    let thread: String
    let directory: CodexDirectory
    let permission: String
    let createdAt: Double
}
struct CodexAttachment: Codable {
    let id: String
    let name: String
    let mime: String
    let base64: String
    // Preserve the wire representation of retained receipts across upgrades.
    // New imports explicitly describe inline text rather than implying a copy
    // exists in the execution folder.
    var transportVersion: Int? = nil
    var coverage: String? = nil
    var sourceBytes: Int? = nil
    var sourceHash: String? = nil
    var data: Data { Data(base64Encoded: base64) ?? Data() }
    var sha256: String { NativeCodex.digest(data) }
    var input: [String: Any] {
        if mime.hasPrefix("image/") { return ["type": "image", "url": "data:" + mime + ";base64," + base64] }
        let parsing = coverage.flatMap { $0 == "text_full" ? nil : $0 }.map { "Local parsing coverage: \($0). Document images, layout, charts, notes and embedded objects are not included; formulas/macros were not executed. Source SHA256: \(sourceHash ?? "unknown").\n" } ?? ""
        let header = transportVersion == 2
            ? "Text attachment supplied inline: \(name)\nUTF-8 content byte count: \(data.count); SHA256: \(sha256)\nThe exact content follows the next line. This attachment was not copied into the task folder; read it here, not by searching for a file. The hash covers only the content bytes, excluding this header.\n--- BEGIN ATTACHMENT CONTENT ---\n"
            : "Attached file: \(name) (SHA256 \(sha256))\n"
        return ["type": "text", "text": parsing + header + String(decoding: data, as: UTF8.self)]
    }
    var inputs: [[String: Any]] {
        guard transportVersion == 3, mime.hasPrefix("image/") else { return [input] }
        return [["type": "text", "text": "Image attachment supplied next: \(name)\nSource SHA256: \(sourceHash ?? sha256). This label identifies the following image; it does not describe its content."], input]
    }
}
struct CodexOwnerResultCheck: Codable {
    let id: String
    let turn: String
    let resultHash: String
    let recordedAt: Double
}
struct CodexSubmission: Codable {
    let id: String
    let thread: String
    let directory: CodexDirectory
    var text: String
    var attachments: [CodexAttachment]
    let model: String
    let effort: String
    let mode: String
    let createdAt: Double
    let source: String?
    let message: String?
    let instructionHash: String?
    var state: String
    var turn: String?
    var queuedSubmission: String?
    var result: String?
    var error: String?
    var sourceContentHash: String?
    var supersedes: String?
    var returnState: String?
    // Optional for historical receipts. Created only after dispatch-time checks;
    // never used as a substitute for the native permission profile or lease.
    var dispatchContext: String?
    var retryOf: String?
    var ownerResultCheck: CodexOwnerResultCheck? = nil
    var validOwnerResultCheck: CodexOwnerResultCheck? {
        guard state == "completed", let turn = turn, let result = result, !result.isEmpty,
              let check = ownerResultCheck, check.turn == turn,
              UUID(uuidString: check.id) != nil, check.recordedAt.isFinite, check.recordedAt > 0,
              check.resultHash == NativeCodex.digest(Data(result.utf8)) else { return nil }
        return check
    }
    var input: [[String: Any]] {
        (dispatchContext.map { [["type": "text", "text": $0]] } ?? []) + [["type": "text", "text": text]] + attachments.flatMap { $0.inputs }
    }
    var businessResult: String {
        guard state == "completed" else { return "not_completed" }
        // This is a report from the executor, not independent artifact proof.
        let pattern = #"(?im)^\s*(?:[-*]\s+)?(?:\*\*)?(?:BUSINESS_RESULT|RESULT)(?:\*\*)?\s*[:=：]\s*(?:\*\*)?(BLOCKED|FAIL(?:ED)?|PARTIAL|PASS)\b"#
        let text = result ?? "", ns = text as NSString
        let reports = (try? NSRegularExpression(pattern: pattern))?.matches(in: text, range: NSRange(location: 0, length: ns.length)).map { ns.substring(with: $0.range(at: 1)).uppercased() } ?? []
        if reports.contains("BLOCKED") { return "blocked" }
        if reports.contains("FAIL") || reports.contains("FAILED") { return "failed" }
        if reports.contains("PARTIAL") { return "partial" }
        return reports.contains("PASS") ? "reported_pass" : "unverified"
    }
    var businessBlocked: Bool { ["blocked", "failed", "partial"].contains(businessResult) }
    var card: [String: Any] {
        ["id": id, "source": source ?? "", "message": message ?? "", "hash": sourceContentHash ?? instructionHash ?? "", "state": state,
         "cwd": directory.path, "model": model, "effort": effort, "result": result ?? "", "error": error ?? "",
         "businessResult": businessResult, "retryable": businessBlocked, "createdAt": createdAt, "retryOf": retryOf ?? ""]
    }
}
struct CodexLedger: Codable {
    var bindings: [String: CodexBinding] = [:]
    var submissions: [CodexSubmission] = []
    var paused: Set<String> = []
    var drafts: [String: [CodexAttachment]] = [:]
    var mode: String = "steer"
    var settings: [String: [String: String]]?
    // A confirmed source discussion may subsequently send directly to this
    // exact binding. Optional for ledgers saved before one-click handoff.
    var handoffTargets: [String: CodexBinding]?
}

// One native-owned connection; only the bundled local renderer can call it.
// Remote website panes never receive this script-message handler.
final class NativeCodex: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    let web: WKWebView
    let resources: URL
    let preferences: URL
    let translate: (String) -> String
    var returnResult: ((String, URL) -> Void)?
    var languageChanged: ((String) -> Bool)?
    var directoryChoiceGeneration = 0
    var process: Process?
    var input: Pipe?
    var output: Pipe?
    var errors: Pipe?
    var nyraAction: ((String) -> Void)?
    var statusMetadataChanged: (() -> Void)?
    var diagnosticTail = ""
    var buffer = Data()
    var requestID = 0
    var lastRequestFailure: String?
    var requestMethods: [Int: String] = [:]
    var requestArguments: [Int: [String: Any]] = [:]
    var callbacks: [Int: ([String: Any]?) -> Void] = [:]
    var selected: [String: Any]?
    var turnID: String?
    var startingTurn = false
    var loadedThread: String?
    var selectionGeneration = 0
    var transportGeneration = 0
    var completedTurns = Set<String>()
    var pendingSource: URL?
    var resultSource: URL?
    var candidateResult = ""
    var draftText = ""
    var restoringThread: String?
    var uncertain = false
    var lockFD: Int32 = -1
    var lastHistoryTurn: String?
    var threadCursor: String?
    var threadRows: [[String: Any]] = []
    var historyLoading = false
    var historyReady = false
    var approvals: [String: [String: Any]] = [:]
    var answeredApprovals = Set<String>()
    var stopRequested = false
    var displayItems: [String: [String: Any]] = [:]
    var displayOrder: [String] = []
    var historyCursor: String?
    var sourceURL: URL?
    var lastResult = ""
    var connected = false
    var pageReady = false
    var pendingUI: [[String: Any]] = []
    var modelIDs = Set<String>()
    var modelCatalog: [[String: Any]] = []
    var ledger = CodexLedger()
    var ledgerReadable = true
    var pendingDirectory: (token: String, directory: CodexDirectory, create: Bool)?
    var artifactSavePanel: NSSavePanel?
    var creatingThread = false
    var submissionPending = false
    var controlledThreads = Set<String>()
    var activeSubmission: String?
    var nextModel = ""
    var nextEffort = ""
    var handoffCandidate: (text: String, source: URL, message: String, hash: String)?
    var handoffChanged: ((CodexSubmission) -> Void)?
    var resumeAfterCreate = false
    var telemetry = CodexTelemetryStore()
    var observationTimer: Timer?
    var observationTick = ProcessInfo.processInfo.systemUptime
    var observationSavedAt = 0.0
    var telemetrySaveError = false
    var usageReading = false
    var runReading = false
    var usageRequestedAt = 0.0
    var usageRetryAfter = 0.0
    var usageBackoff = 300.0
    var usageGeneration = 0
    var accountVerified = false
    let telemetrySessionIdentity = UUID().uuidString
    var usageErrors: [String: String] = [:]

    var ownerDesktopRunning: () -> Bool = { !NSRunningApplication.runningApplications(withBundleIdentifier: "com.openai.codex").isEmpty }
    var isBusy: Bool { startingTurn || turnID != nil }
    var threadID: String? { selected?["id"] as? String }
    var cwd: String? { selected?["cwd"] as? String }

    init(resources: URL, preferences: URL, translate: @escaping (String) -> String) {
        self.resources = resources; self.preferences = preferences; self.translate = translate
        let config = WKWebViewConfiguration(); config.websiteDataStore = .nonPersistent()
        web = WKWebView(frame: .zero, configuration: config)
        super.init()
        restoreLedger()
        restoreTelemetry(); startObservationTimer()
        config.userContentController.add(self, name: "twosCodex")
        web.navigationDelegate = self
        web.loadFileURL(resources.appendingPathComponent("native_codex/index.html"), allowingReadAccessTo: resources)
    }
    func emit(_ kind: String, _ payload: [String: Any] = [:]) {
        let message: [String: Any] = ["kind": kind, "payload": payload]
        guard pageReady else { pendingUI.append(message); return }
        guard let data = try? JSONSerialization.data(withJSONObject: message), let json = String(data: data, encoding: .utf8) else { return }
        web.evaluateJavaScript("window.twosReceive(\(json))", completionHandler: nil)
    }
    func notice(_ text: String) { emit("notice", ["text": translate(text)]) }
    func controlState() {
        statusMetadataChanged?()
        emit("control", ["connected": connected, "busy": isBusy, "awaitingTurn": startingTurn && turnID == nil, "desktopRunning": ownerDesktopRunning(), "threadId": threadID ?? "", "uncertain": uncertain, "historyReady": historyReady, "controllable": canControl, "controlVerified": threadID.map { controlledThreads.contains($0) } ?? false, "submitting": submissionPending, "mode": ledger.mode, "turnId": turnID ?? "", "nextModel": nextModel, "nextEffort": nextEffort, "stopRequested": stopRequested, "waitingRequests": approvals.count - answeredApprovals.count, "answeringRequests": answeredApprovals.count, "cwd": cwd ?? "", "actualModel": selected?["model"] ?? "", "permission": threadID.flatMap { ledger.bindings[$0]?.permission } ?? ""])
    }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame,
              message.frameInfo.request.url?.standardizedFileURL == resources.appendingPathComponent("native_codex/index.html").standardizedFileURL,
              let value = message.body as? [String: Any], let action = value["action"] as? String else { return }
        switch action {
        case "nyra": nyraAction?("toggle")
        case "ready":
            nyraAction?("status")
            pageReady = true
            let queued = pendingUI; pendingUI = []
            for event in queued { emit(event["kind"] as! String, event["payload"] as? [String: Any] ?? [:]) }
            publishLanguage(); controlState(); restoreDraft(); publishTelemetry()
            if connected {
                emit("models", ["items": modelCatalog])
                emit("threads", ["items": threadRows, "more": threadCursor != nil])
                if let thread = selected { emit("thread", ["thread": thread]); emitDraft(); loadHistory(older: false) }
                publishQueue(); publishAttachments(); publishDisplaySnapshot()
                for (key, request) in approvals { emit("approval", approvalPayload(key, request)) }
            }
        case "language":
            guard let locale = value["locale"] as? String, ["zh-CN", "en-US"].contains(locale), languageChanged?(locale) == true else { return }
            publishLanguage()
        case "directoryMode": directoryChoiceGeneration += 1; pendingDirectory = nil
        case "connect": connect()
        case "usage": refreshUsage()
        case "cancelUsage": usageGeneration += 1; usageReading = false; publishTelemetry()
        case "runStatus": refreshRunObservation()
        case "reconnect":
            guard uncertain || !isBusy else { return }
            reconnect()
        case "refresh": if connected && !isBusy { listThreads(); if let id = threadID { selectThread(id) } }; controlState()
        case "moreThreads": listThreads(older: true)
        case "select": if let id = value["id"] as? String { selectThread(id) }
        case "send": submitComposer(value)
        case "newTask":
            directoryChoiceGeneration += 1; pendingDirectory = nil
            emit("directoryCleared", [:]); emit("newTask", ["busy": isBusy])
        case "chooseDirectory": chooseDirectory(create: value["create"] as? Bool == true, isolated: value["isolated"] as? Bool != false)
        case "cancelDirectory": directoryChoiceGeneration += 1; pendingDirectory = nil; handoffCandidate = nil
        case "confirmDirectory": confirmDirectory(token: value["token"] as? String ?? "", model: value["model"] as? String ?? "", effort: value["effort"] as? String ?? "")
        case "confirmHandoff": confirmHandoff(model: value["model"] as? String ?? "", effort: value["effort"] as? String ?? "", hash: value["hash"] as? String ?? "")
        case "cancelHandoff": handoffCandidate = nil
        case "attach": chooseAttachments()
        case "attachment":
            if value["threadId"] as? String == threadID { importAttachment(name: value["name"] as? String ?? "", mime: value["mime"] as? String ?? "", base64: value["base64"] as? String ?? "") }
        case "removeAttachment":
            if let id = threadID, let item = value["id"] as? String { ledger.drafts[id]?.removeAll(where: { $0.id == item }); if persistLedger() { publishAttachments() } }
        case "mode": if let mode = value["mode"] as? String, ["steer", "queue"].contains(mode) { ledger.mode = mode; persistLedger(); controlState() }
        case "model":
            nextModel = value["model"] as? String ?? ""; nextEffort = value["effort"] as? String ?? ""
            if let id = threadID { if ledger.settings == nil { ledger.settings = [:] }; ledger.settings?[id] = ["model": nextModel, "effort": nextEffort]; persistLedger() }
            controlState()
        case "editQueue": editQueue(value)
        case "deleteQueue": deleteQueue(value["id"] as? String ?? "")
        case "resumeQueue":
            if let id = threadID, !isBusy, !uncertain { ledger.paused.remove(id); if persistLedger() { publishQueue(); dispatchNext() } }
        case "inspectDelivery": reconcileDelivery()
        case "startSavedQueue":
            if let id = value["id"] as? String { startAcceptedQueue(id, recovering: true) }

        case "interrupt": interrupt()
        case "workspace":
            if let cwd = cwd, FileManager.default.fileExists(atPath: cwd) { NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: cwd) }
        case "artifacts": if value["threadId"] as? String == threadID { listArtifacts() }
        case "artifact": artifactAction(value)
        case "confirmResult": confirmResult(value)
        case "copy":
            if let text = value["text"] as? String, text.utf8.count <= 2_000_000 {
                NSPasteboard.general.clearContents(); NSPasteboard.general.setString(text, forType: .string)
            }
        case "answer": answer(value)
        case "draft":
            if let text = value["text"] as? String, text.utf8.count <= 200_000, value["threadId"] as? String == threadID { saveDraft(text) }
        case "more": loadHistory(older: true)
        case "return":
            if !lastResult.isEmpty, let source = resultSource { returnResult?(lastResult, source) }
        default: break
        }
    }
    func readMap(_ name: String) -> [String: String] {
        guard let data = try? Data(contentsOf: preferences.appendingPathComponent(name)),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: String] else { return [:] }
        return value
    }
    @discardableResult func saveMap(_ value: [String: String], _ name: String) -> Bool {
        do { try NativeWorkbench.save(value, at: preferences.appendingPathComponent(name)); return true }
        catch { notice("The draft could not be saved. Keep this window open and copy it before quitting."); return false }
    }
    func saveDraft(_ text: String) {
        draftText = text
        var value = ["text": text, "thread": threadID ?? ""]
        if let sourceURL = sourceURL { value["source"] = sourceURL.absoluteString }
        saveMap(value, "codex-draft.json")
        if let id = threadID, let bytes = try? JSONSerialization.data(withJSONObject: value), let encoded = String(data: bytes, encoding: .utf8) {
            var drafts = readMap("codex-thread-drafts.json"); drafts[id] = encoded
            saveMap(drafts, "codex-thread-drafts.json")
        }
    }
    func restoreDraft() {
        let value = readMap("codex-draft.json")
        sourceURL = value["source"].flatMap(URL.init(string:)); draftText = value["text"] ?? ""
        restoringThread = value["thread"].flatMap { $0.isEmpty ? nil : $0 }
        emitDraft(savedThread: restoringThread)
    }
    func emitDraft(savedThread: String? = nil) {
        emit("draft", ["text": draftText, "source": sourceURL?.absoluteString ?? "", "savedThread": savedThread ?? ""])
    }
    func legacyStage(_ text: String, source: URL) {
        guard !isBusy && !uncertain else { notice("Finish or stop the current Codex turn before handing off another request."); return }
        // Preserve a user's existing draft instead of replacing it on handoff.
        sourceURL = source; saveDraft(draftText.isEmpty ? text : draftText + "\n\n" + text)
        emitDraft()
        notice("Review the instructions and destination conversation, then choose Send to Codex.")
    }
    func bindOrigin(_ turn: String) {
        guard let id = threadID, let source = pendingSource else { return }
        var origins = readMap("codex-return-origins.json"); origins[id + "/" + turn] = source.absoluteString
        saveMap(origins, "codex-return-origins.json")
    }
    func publishResult() {
        let latest = ledger.submissions.last { $0.thread == threadID && ["completed", "failed", "interrupted"].contains($0.state) }
        emit("result", ["available": !lastResult.isEmpty && resultSource != nil, "source": resultSource?.absoluteString ?? "",
                        "businessResult": latest?.businessResult ?? "", "transport": latest?.state ?? "",
                        "submissionID": latest?.id ?? "", "turnID": latest?.turn ?? "",
                        "resultHash": latest?.result.map { Self.digest(Data($0.utf8)) } ?? "",
                        "ownerResultConfirmed": latest?.validOwnerResultCheck != nil])
        if latest != nil { listArtifacts(automatic: true) }
    }
    func confirmResult(_ value: [String:Any]) {
        guard !isBusy, !uncertain, let thread = threadID, value["threadId"] as? String == thread,
              let id = value["id"] as? String, let record = ledger.submissions.last(where:{$0.id == id && $0.thread == thread}),
              record.state == "completed", let turn = record.turn, value["turn"] as? String == turn,
              let result = record.result, !result.isEmpty, value["resultHash"] as? String == Self.digest(Data(result.utf8)),
              record.validOwnerResultCheck == nil, let window = web.window else { return }
        let alert = NSAlert()
        alert.messageText = translate("Confirm this result after checking it")
        alert.informativeText = translate("This records your check of this result only. It does not start work, change the executor's report, or accept the whole project.") + "\n" + record.directory.path
        alert.addButton(withTitle:translate("I checked this result")); alert.addButton(withTitle:translate("Cancel"))
        alert.beginSheetModal(for:window) { [weak self] response in
            guard let self = self, response == .alertFirstButtonReturn, !self.isBusy, !self.uncertain, self.threadID == thread,
                  let current = self.ledger.submissions.last(where:{$0.id == id}), current.turn == turn,
                  current.state == "completed", current.result == result, current.validOwnerResultCheck == nil else { return }
            let check = CodexOwnerResultCheck(id:UUID().uuidString,turn:turn,resultHash:Self.digest(Data(result.utf8)),recordedAt:Date().timeIntervalSince1970)
            guard self.changeSubmission(id,{$0.ownerResultCheck = check}) else { return }
            self.publishResult(); self.statusMetadataChanged?()
        }
    }
    @discardableResult func markPending(_ turn: String = "") -> Bool {
        guard let id = threadID else { return false }
        var pending = readMap("codex-pending.json")
        pending[id] = turn.isEmpty ? "unconfirmed:" + (lastHistoryTurn ?? "") : turn
        return saveMap(pending, "codex-pending.json")
    }
    func clearPending() {
        guard let id = threadID else { return }
        var pending = readMap("codex-pending.json"); pending.removeValue(forKey: id); saveMap(pending, "codex-pending.json")
        uncertain = false
    }
    func acquireLock(_ id: String) -> Bool {
        // One TWOS writer for this home/thread, including separate TWOS profiles.
        let home = ProcessInfo.processInfo.environment["CODEX_HOME"] ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".codex").path
        let key = Data(home.utf8).base64EncodedString().replacingOccurrences(of: "/", with: "_")
        guard let canonical = realpath(FileManager.default.temporaryDirectory.path, nil) else { return false }
        let base = URL(fileURLWithPath: String(cString: canonical)); free(canonical)
        let root = base.appendingPathComponent("twos-codex-locks-\(getuid())/" + key)
        do { try NativeWorkbench.safeDirectory(root) } catch { return false }
        let fd = Darwin.open(root.appendingPathComponent(id + ".lock").path, O_CREAT | O_RDWR | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard fd >= 0 else { return false }
        guard flock(fd, LOCK_EX | LOCK_NB) == 0 else { Darwin.close(fd); return false }
        lockFD = fd; return true
    }
    func releaseLock() { if lockFD >= 0 { flock(lockFD, LOCK_UN); Darwin.close(lockFD); lockFD = -1 } }
    func reconnect() {
        guard !isBusy else { reconcileDelivery(); return }
        let child = process
        if child?.isRunning == true {
            notice("Closing this connection before reading the saved conversation again. No request will be resent.")
            disconnect()
            DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
                guard child?.isRunning != true else { return }; self?.connect()
            }
        } else { connect() }
    }
    func connect() {
        guard process?.isRunning != true else { listThreads(); return }
        accountVerified = false; usageReading = false; usageGeneration += 1; usageRequestedAt = 0
        let paths = ["/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex", "/Applications/Codex.app/Contents/Resources/codex"]
        guard let path = paths.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            notice("The installed Codex command could not be found. Install the official Codex App first."); return
        }
        let child = Process(); child.executableURL = URL(fileURLWithPath: path)
        // This profile is passed only to this process. User config is not edited.
        // It excludes unrelated user files; runtime roots are bound at resume.
        child.arguments = ["app-server", "--listen", "stdio://", "-c", "default_permissions=\"twos-integrated\"", "-c", "features.multi_agent=false", "-c", "features.apps=false", "-c", "features.plugins=false", "-c", "mcp_servers={}", "-c", "web_search=\"disabled\"", "-c", "allow_login_shell=false", "-c", "shell_environment_policy.inherit=\"core\"",
            "-c", "permissions.twos-integrated.filesystem={\":root\"=\"deny\",\":minimal\"=\"read\",\":workspace_roots\"={\".\"=\"write\",\".git\"=\"read\",\".codex\"=\"deny\",\".aws\"=\"deny\",\".ssh\"=\"deny\",\".env\"=\"deny\"}}",
            "-c", "permissions.twos-integrated.network.enabled=false"]
        // Program installations are readable; user profiles and unrelated data
        // are still outside the selected workspace boundary.
        if let index = child.arguments!.firstIndex(where: { $0.hasPrefix("permissions.twos-integrated.filesystem=") }) {
            var table = String(child.arguments![index].dropLast())
            for path in ["/usr/local/bin/node", "/opt/homebrew/bin/node", "/usr/bin/python3", "/System/Library/OpenSSL/openssl.cnf"] where FileManager.default.fileExists(atPath: path) {
                let actual = URL(fileURLWithPath: path).resolvingSymlinksInPath().path
                guard ["/usr/local/", "/opt/homebrew/", "/usr/bin/", "/System/Library/", "/Applications/", "/Library/Developer/"].contains(where: { actual.hasPrefix($0) }) else { continue }
                let escaped = actual.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
                table += ",\"" + escaped + "\"=\"read\""
            }
            child.arguments![index] = table + "}"
        }
        var env = ProcessInfo.processInfo.environment
        env.removeValue(forKey: "OPENAI_API_KEY"); env.removeValue(forKey: "CODEX_ACCESS_TOKEN")
        child.environment = env
        child.currentDirectoryURL = FileManager.default.temporaryDirectory
        transportGeneration += 1; let generation = transportGeneration
        input = Pipe(); output = Pipe(); buffer = Data()
        child.standardInput = input; child.standardOutput = output
        errors = Pipe(); diagnosticTail = ""; child.standardError = errors
        errors!.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            let text = String(decoding: data, as: UTF8.self)
            DispatchQueue.main.async {
                guard let self = self, self.transportGeneration == generation else { return }
                let safe = text.split(separator: "\n").map { line in
                    line.range(of: "(?i)(bearer |api.key|access.token|refresh.token|authorization)", options: .regularExpression) == nil ? String(line) : "[credential-related diagnostic omitted]"
                }.joined(separator: "\n")
                self.diagnosticTail = String((self.diagnosticTail + safe + "\n").suffix(6000))
            }
        }
        output!.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { guard self?.transportGeneration == generation else { return }; self?.receive(data) }
        }
        child.terminationHandler = { [weak self] ended in
            DispatchQueue.main.async {
                guard let self = self, self.process === ended else { return }
                self.connected = false
                self.usageReading = false; self.usageGeneration += 1; self.usageErrors["account"] = "network"; self.saveTelemetry(); self.publishTelemetry()
                let unresolved = self.isBusy || self.uncertain
                self.uncertain = unresolved; self.releaseLock()
                self.turnID = nil; self.startingTurn = false; self.loadedThread = nil; self.controlledThreads.removeAll(); self.submissionPending = false
                for item in self.ledger.submissions where !["completed", "failed", "interrupted", "cancelled", "rejected"].contains(item.state) { self.ledger.paused.insert(item.thread) }
                self.persistLedger(); self.publishQueue()
                self.callbacks.removeAll(); self.requestMethods.removeAll(); self.requestArguments.removeAll(); self.approvals.removeAll(); self.answeredApprovals.removeAll(); self.stopRequested = false; self.controlState()
                self.emit("clearApprovals")
                self.notice(unresolved ? "Codex disconnected during execution. The request will not be sent again automatically. Reconnect and inspect the saved conversation." : "Codex disconnected. Reconnect to view your saved conversations.")
                if !self.diagnosticTail.isEmpty && ended.terminationStatus != 0 {
                    self.emit("notice", ["text": self.translate("The local Codex service stopped. Expand the details for its reported cause."), "detail": self.diagnosticTail])
                }
            }
        }
        process = child
        do { try child.run() } catch { notice("Codex could not start. Your saved conversations have not been changed."); return }
        request("initialize", ["clientInfo": ["name": "twos_integrated_workbench", "title": "Tianma Work OS", "version": "1.0.3"], "capabilities": ["experimentalApi": true]]) { [weak self] result in
            guard let self = self else { return }
            guard result != nil else { self.disconnect(); return }
            self.write(["method": "initialized"]); self.connected = true; self.controlState(); self.listThreads(); self.refreshUsage()
            if let id = self.threadID ?? self.restoringThread { self.selectThread(id) }
            self.request("model/list", ["limit": 100]) { result in
                let models = result?["data"] as? [[String: Any]] ?? []
                self.modelCatalog = models; self.modelIDs = Set(models.compactMap { $0["model"] as? String })
                self.emit("models", ["items": models])
            }
        }
    }
    func write(_ object: [String: Any]) {
        guard let input = input, process?.isRunning == true, let bytes = try? JSONSerialization.data(withJSONObject: object) else { return }
        do { try input.fileHandleForWriting.write(contentsOf: bytes + Data([10])) }
        catch { notice("Codex did not receive the request. Inspect the conversation before retrying.") }
    }
    func request(_ method: String, _ params: [String: Any], completion: @escaping ([String: Any]?) -> Void) {
        requestID += 1; let id = requestID; let generation = transportGeneration; callbacks[id] = completion; requestMethods[id] = method; requestArguments[id] = params
        write(["id": id, "method": method, "params": params])
        DispatchQueue.main.asyncAfter(deadline: .now() + 40) { [weak self] in
            guard let self = self, self.transportGeneration == generation, let callback = self.callbacks.removeValue(forKey: id) else { return }
            if !method.hasPrefix("account/") { self.notice("Codex has not confirmed this request. Do not resend it until the conversation has been checked.") }
            self.lastRequestFailure = "timeout"; self.requestMethods.removeValue(forKey: id); self.requestArguments.removeValue(forKey: id); callback(nil)
        }
    }
    func receive(_ bytes: Data) {
        buffer.append(bytes)
        guard buffer.count <= 24_000_000 else { notice("A Codex event was too large to display. The saved conversation remains available."); buffer.removeAll(); uncertain = true; controlState(); return }
        while let index = buffer.firstIndex(of: 10) {
            let line = Data(buffer[..<index]); buffer.removeSubrange(...index)
            guard let value = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else { continue }
            if value["method"] == nil, let id = value["id"] as? Int, let callback = callbacks.removeValue(forKey: id) {
                let replyMethod = requestMethods.removeValue(forKey: id) ?? ""; requestArguments.removeValue(forKey: id); lastRequestFailure = nil
                if let error = value["error"] as? [String: Any] {
                    lastRequestFailure = error["message"] as? String
                    if !replyMethod.hasPrefix("account/") { emit("notice", ["text": translate("The local Codex service rejected this request. Saved work is retained."), "code": error["code"] as? Int ?? -1, "detail": error["message"] as? String ?? ""]) }
                    callback(nil)
                } else { callback(value["result"] as? [String: Any] ?? [:]) }
                continue
            }
            guard let method = value["method"] as? String, let params = value["params"] as? [String: Any] else { continue }
            if accountNotification(method, params) { continue }
            observeEvent(method, params, requestID: value["id"])
            let target = params["threadId"] as? String
            if let id = value["id"] {
                guard target == threadID, !uncertain, activeSubmission != nil, let turn = params["turnId"] as? String, turn == turnID,
                      ["item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/permissions/requestApproval", "item/tool/requestUserInput"].contains(method) else {
                    write(["id": id, "error": ["code": -32601, "message": "Request not supported by this client"]]); continue
                }
                let key = UUID().uuidString
                let duplicate = approvals.first { Self.sameRequestID($0.value["id"], id) }
                if duplicate != nil { continue }
                approvals[key] = ["id": id, "method": method, "params": params]
                emit("approval", approvalPayload(key, approvals[key]!)); controlState(); continue
            }
            guard target == threadID else { continue }
            if method == "serverRequest/resolved" {
                for (key, request) in approvals where Self.sameRequestID(request["id"], params["requestId"]) {
                    approvals.removeValue(forKey: key); answeredApprovals.remove(key); emit("answered", ["key": key])
                }
                controlState(); continue
            }
            if method == "turn/started", let turn = params["turn"] as? [String: Any], let id = turn["id"] as? String,
               !startingTurn, turnID == nil, controlledThreads.contains(target ?? "") {
                turnID = id; uncertain = true; activeSubmission = nil; pendingSource = nil; candidateResult = ""; resultSource = nil
                if let target = target { ledger.paused.insert(target) }; persistLedger(); markPending(id)
                notice("Another input started this turn. Its control and approvals are not assigned to this delivery; queued work is paused."); controlState()
            }
            if method == "turn/started", let turn = params["turn"] as? [String: Any], let id = turn["id"] as? String, startingTurn || turnID == id {
                if !completedTurns.contains(id) {
                    turnID = id; startingTurn = false; markPending(id)
                    // userMessage.clientId below, not a coincident turn event,
                    // proves which immutable input actually started this turn.
                    controlState()
                }
            }
            if method == "item/started", let item = params["item"] as? [String: Any], item["type"] as? String == "userMessage",
               let eventTurn = params["turnId"] as? String, eventTurn == turnID {
                if let clientID = item["clientId"] as? String, let record = ledger.submissions.first(where: { $0.id == clientID && $0.thread == threadID }) {
                    if record.id == activeSubmission { bindOrigin(eventTurn) }
                    changeSubmission(clientID) { $0.turn = eventTurn; $0.state = $0.mode == "steer" ? "accepted" : "running" }
                } else {
                    uncertain = true; pendingSource = nil
                    if let target = target { ledger.paused.insert(target) }; persistLedger()
                    notice("An input from another client appeared in this turn. Automatic handoff and queued dispatch are paused pending control verification."); controlState()
                }
            }
            if method == "turn/completed", let turn = params["turn"] as? [String: Any], let id = turn["id"] as? String, id == turnID || startingTurn {
                completedTurns.insert(id); bindOrigin(id)
                if turn["status"] as? String == "completed" {
                    lastResult = candidateResult
                    resultSource = readMap("codex-return-origins.json")[((threadID ?? "") + "/" + id)].flatMap(URL.init(string:))
                }
                for index in ledger.submissions.indices where ledger.submissions[index].thread == threadID && ledger.submissions[index].turn == id && !["rejected", "cancelled"].contains(ledger.submissions[index].state) {
                    ledger.submissions[index].state = turn["status"] as? String ?? "failed"
                    ledger.submissions[index].result = candidateResult
                    ledger.submissions[index].error = (turn["error"] as? [String: Any])?["message"] as? String
                }
                if let thread = threadID, turn["status"] as? String != "completed" || ledger.submissions.contains(where: { $0.thread == thread && $0.turn == id && $0.businessBlocked }) { ledger.paused.insert(thread) }
                if persistLedger() {
                    let finished = ledger.submissions.filter { $0.thread == threadID && $0.turn == id && !["rejected", "cancelled"].contains($0.state) }
                    for record in finished { handoffChanged?(record) }
                }
                activeSubmission = nil
                lastHistoryTurn = id; turnID = nil; startingTurn = false; approvals.removeAll(); answeredApprovals.removeAll(); stopRequested = false; clearPending(); releaseLock(); controlState(); publishResult(); publishQueue()
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in self?.dispatchNext() }
                emit("turnCompleted", ["status": turn["status"] ?? "unknown", "error": turn["error"] ?? NSNull()]); continue
            }
            if let eventTurn = params["turnId"] as? String, eventTurn != turnID { continue }
            if method == "item/started" || method == "item/completed", let item = params["item"] as? [String: Any] {
                if item["type"] as? String == "reasoning" {
                    rememberDisplayItem(["id": item["id"] ?? "", "type": "reasoning", "summary": item["summary"] ?? []])
                    emit("summary", ["id": item["id"] ?? "", "summary": item["summary"] ?? []]); continue
                }
                if method == "item/completed" {
                    for (key, request) in approvals where (request["params"] as? [String: Any])?["itemId"] as? String == item["id"] as? String {
                        approvals.removeValue(forKey: key); answeredApprovals.remove(key); emit("answered", ["key": key])
                    }
                    controlState()
                }
                if method == "item/completed", item["type"] as? String == "agentMessage", let text = item["text"] as? String {
                    if item["phase"] as? String != "commentary" { candidateResult = text }
                }
            }
            if method.hasPrefix("item/reasoning/") && method != "item/reasoning/summaryTextDelta" { continue }
            if ["item/started", "item/completed", "item/agentMessage/delta", "item/commandExecution/outputDelta", "item/fileChange/outputDelta", "item/reasoning/summaryTextDelta", "turn/plan/updated", "turn/diff/updated", "item/mcpToolCall/progress", "error"].contains(method) {
                rememberDisplayEvent(method, params)
                emit("event", ["method": method, "params": params])
            }
        }
    }
    func listThreads(older: Bool = false) {
        guard connected else { return }
        var params: [String: Any] = ["limit": 50, "sortKey": "updated_at", "useStateDbOnly": true]
        if older { guard let cursor = threadCursor else { return }; params["cursor"] = cursor }
        request("thread/list", params) { [weak self] result in
            guard let self = self, let result = result else { return }
            let rows = result["data"] as? [[String: Any]] ?? []
            if older { self.threadRows += rows } else { self.threadRows = rows }
            self.threadCursor = result["nextCursor"] as? String
            self.emit("threads", ["items": self.threadRows, "more": self.threadCursor != nil])
        }
    }
    func selectThread(_ id: String) {
        guard connected, !isBusy, !submissionPending, UUID(uuidString: id) != nil else {
            notice("The current task is still running. You can prepare a new folder now and switch after it finishes."); controlState(); return
        }
        selectionGeneration += 1; let generation = selectionGeneration
        request("thread/read", ["threadId": id, "includeTurns": false]) { [weak self] result in
            guard let self = self, self.selectionGeneration == generation, !self.isBusy, let thread = result?["thread"] as? [String: Any], thread["id"] as? String == id else { return }
            let previous = self.threadID
            if previous != id {
                if previous != nil { self.saveDraft(self.draftText) }
                if let saved = self.readMap("codex-thread-drafts.json")[id], let bytes = saved.data(using: .utf8),
                   let value = try? JSONSerialization.jsonObject(with: bytes) as? [String: String] {
                    self.draftText = value["text"] ?? ""; self.sourceURL = value["source"].flatMap(URL.init(string:))
                } else if previous != nil || (self.restoringThread != nil && self.restoringThread != id) {
                    self.draftText = ""; self.sourceURL = nil
                }
            }
            self.displayItems.removeAll(); self.displayOrder.removeAll(); self.approvals.removeAll(); self.answeredApprovals.removeAll(); self.emit("clearApprovals")
            self.selected = thread; self.lastResult = ""; self.resultSource = nil; self.historyCursor = nil; self.historyLoading = false; self.historyReady = false
            self.uncertain = self.readMap("codex-pending.json")[id] != nil
            self.nextModel = self.ledger.settings?[id]?["model"] ?? thread["model"] as? String ?? ""; self.nextEffort = self.ledger.settings?[id]?["effort"] ?? thread["reasoningEffort"] as? String ?? ""
            self.saveDraft(self.draftText)
            self.publishQueue(); self.publishAttachments()
            self.emit("thread", ["thread": thread]); self.emitDraft(); self.publishResult(); self.controlState(); self.loadHistory(older: false)
        }
    }
    func loadHistory(older: Bool) {
        guard let id = threadID, !historyLoading else { return }
        let generation = selectionGeneration; historyLoading = true
        var params: [String: Any] = ["threadId": id, "limit": 10, "sortDirection": "desc", "itemsView": "full"]
        if older { guard let cursor = historyCursor else { historyLoading = false; return }; params["cursor"] = cursor }
        request("thread/turns/list", params) { [weak self] result in
            guard let self = self, self.threadID == id, self.selectionGeneration == generation else { return }
            self.historyLoading = false
            guard let result = result else { return }
            self.historyCursor = result["nextCursor"] as? String
            var turns = result["data"] as? [[String: Any]] ?? []
            for n in turns.indices {
                var items = turns[n]["items"] as? [[String: Any]] ?? []
                for i in items.indices where items[i]["type"] as? String == "reasoning" {
                    items[i] = ["id": items[i]["id"] ?? "", "type": "reasoning", "summary": items[i]["summary"] ?? []]
                }
                turns[n]["items"] = items
            }
            if !older {
                self.lastHistoryTurn = turns.first?["id"] as? String
                let pending = self.readMap("codex-pending.json")[id]
                if let pending = pending {
                    let candidate = pending.hasPrefix("unconfirmed:") ? turns.first : turns.first(where: { $0["id"] as? String == pending })
                    if let turn = candidate, let tid = turn["id"] as? String,
                       self.confirmedHistoryTerminal(turn) != nil,
                       !pending.hasPrefix("unconfirmed:") || tid != String(pending.dropFirst(12)) { self.clearPending() }
                }
                self.historyReady = true
                if self.uncertain { self.notice("The last execution has no confirmed final state. Inspect its history; TWOS will not repeat it.") }
                self.controlState()
                self.reconcileSavedInputs(turns)
            }
            if self.lastResult.isEmpty {
                let origins = self.readMap("codex-return-origins.json")
                for turn in turns where self.confirmedHistoryTerminal(turn) == "completed" {
                    guard let tid = turn["id"] as? String, let source = origins[id + "/" + tid].flatMap(URL.init(string:)) else { continue }
                    let items = turn["items"] as? [[String: Any]] ?? []
                    if let item = items.last(where: { $0["type"] as? String == "agentMessage" && $0["phase"] as? String != "commentary" }), let text = item["text"] as? String, !text.isEmpty {
                        self.lastResult = text; self.resultSource = source; break
                    }
                }
            }
            self.reconcileObservations(thread: id, turns: turns)
            self.emit("history", ["turns": turns, "older": older, "more": self.historyCursor != nil]); self.publishDisplaySnapshot(); self.publishResult()
        }
    }
    func sendTurn(_ raw: String, model: String?) {
        submitComposer(["text": raw, "model": model ?? nextModel, "effort": nextEffort, "mode": ledger.mode])
    }
    func interrupt() {
        guard connected, !uncertain, !stopRequested, activeSubmission != nil,
              let id = threadID, controlledThreads.contains(id), let turn = turnID else { return }
        stopRequested = true; controlState()
        request("turn/interrupt", ["threadId": id, "turnId": turn]) { [weak self] result in
            guard let self = self, self.threadID == id, self.turnID == turn else { return }
            if result == nil { self.stopRequested = false; self.notice("Stop has not been confirmed. Inspect the current turn before trying again.") }
            self.controlState() // Only turn/completed confirms the terminal state.
        }
    }
    static func sameRequestID(_ a: Any?, _ b: Any?) -> Bool {
        guard let a = a, let b = b else { return false }
        return (a as? String != nil && a as? String == b as? String) || (a as? Int != nil && a as? Int == b as? Int)
    }
    func approvalPayload(_ key: String, _ request: [String: Any]) -> [String: Any] {
        let p = request["params"] as? [String: Any] ?? [:]
        let method = request["method"] as? String ?? ""
        // This workbench never grants broader roots, network access, or a
        // persistent approval rule. Ordinary in-scope decisions stay usable.
        let extra = p["additionalPermissions"] as? [String: Any] ?? [:]
        let root = threadID.flatMap { ledger.bindings[$0] }
        let scopeValid = root.map { binding in
            validBinding(binding) && cwd == binding.directory.path && ["cwd", "grantRoot"].allSatisfy { name in
                guard let raw = p[name] as? String else { return true }
                guard let canonical = Self.canonicalArtifactPath(raw) else { return false }
                return canonical == binding.directory.path || canonical.hasPrefix(binding.directory.path + "/")
            }
        } ?? false
        let expanded = !scopeValid || !extra.isEmpty || p["networkApprovalContext"] as? [String: Any] != nil || method == "item/permissions/requestApproval"
        let offered = p["availableDecisions"] as? [Any] ?? ["accept", "decline", "cancel"]
        let decisions = offered.compactMap { $0 as? String }.filter { ["accept", "decline", "cancel"].contains($0) && (!expanded || $0 != "accept") }
        return ["key": key, "method": method, "params": p, "decisions": decisions, "scopeExpansion": expanded, "answering": answeredApprovals.contains(key)]
    }
    func answer(_ value: [String: Any]) {
        guard connected, !uncertain, activeSubmission != nil, let key = value["key"] as? String,
              !answeredApprovals.contains(key), let request = approvals[key],
              let params = request["params"] as? [String: Any], params["threadId"] as? String == threadID,
              params["turnId"] as? String == turnID, let method = request["method"] as? String, let id = request["id"] else { return }
        var result: [String: Any] = [:]
        if method == "item/tool/requestUserInput" {
            guard let responses = value["answers"] as? [String: [String]] else { return }
            let questions = params["questions"] as? [[String: Any]] ?? []
            guard questions.allSatisfy({ q in q["id"].flatMap { responses[$0 as? String ?? ""] } != nil }) else { return }
            result["answers"] = Dictionary(uniqueKeysWithValues: questions.compactMap { question -> (String, [String: [String]])? in
                guard let name = question["id"] as? String else { return nil }
                return (name, ["answers": responses[name] ?? []])
            })
        } else if method == "item/permissions/requestApproval" {
            result = ["permissions": [:], "scope": "turn"]
        } else {
            let decision = value["decision"] as? String ?? (value["accept"] as? Bool == true ? "accept" : "decline")
            guard (approvalPayload(key, request)["decisions"] as? [String] ?? []).contains(decision) else { return }
            result = ["decision": decision]
        }
        answeredApprovals.insert(key)
        write(["id": id, "result": result]); emit("approvalPending", ["key": key]); controlState()
        // Keep the scope until serverRequest/resolved or item completion; a
        // sent response alone is not proof that the service accepted it.
    }
    func disconnect() {
        guard !isBusy else { notice("Stop is a separate action. Finish or explicitly stop this turn before disconnecting."); return }
        let child = process
        try? input?.fileHandleForWriting.close()
        DispatchQueue.main.asyncAfter(deadline: .now() + 4) { if child?.isRunning == true { child?.terminate() } }
    }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.request.url?.standardizedFileURL == resources.appendingPathComponent("native_codex/index.html").standardizedFileURL { decisionHandler(.allow); return }
        if action.navigationType == .linkActivated, let url = action.request.url, ["https", "http"].contains(url.scheme ?? "") { NSWorkspace.shared.open(url) }
        decisionHandler(.cancel)
    }
}

extension NativeCodex {
    static func digest(_ bytes: Data) -> String { SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined() }
    var canControl: Bool { threadID.flatMap { ledger.bindings[$0] } != nil && ledgerReadable }
    var draftAttachments: [CodexAttachment] { ledger.drafts[threadID ?? ""] ?? [] }
    func restoreLedger() {
        let file = preferences.appendingPathComponent("codex-deliveries.json")
        guard FileManager.default.fileExists(atPath: file.path) else { return }
        do {
            ledger = try JSONDecoder().decode(CodexLedger.self, from: Data(contentsOf: file))
            // Restart is observation, never an instruction to replay a queue.
            for item in ledger.submissions where !["completed", "failed", "interrupted", "cancelled", "rejected"].contains(item.state) { ledger.paused.insert(item.thread) }
            for index in ledger.submissions.indices where ledger.submissions[index].returnState == "sending" { ledger.submissions[index].returnState = "unknown" }
        } catch { ledgerReadable = false; notice("The saved delivery records could not be read. Execution is paused; no input has been replayed.") }
    }
    @discardableResult func persistLedger() -> Bool {
        guard ledgerReadable else { return false }
        do {
            try NativeWorkbench.safeDirectory(preferences)
            let file = preferences.appendingPathComponent("codex-deliveries.json")
            try JSONEncoder().encode(ledger).write(to: file, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
            return true
        } catch { notice("Delivery could not be saved. No new request will be sent. Keep this window open."); return false }
    }
    @discardableResult func changeSubmission(_ id: String, _ change: (inout CodexSubmission) -> Void) -> Bool {
        guard let index = ledger.submissions.firstIndex(where: { $0.id == id }) else { return false }
        let previous = ledger.submissions[index]; change(&ledger.submissions[index])
        guard persistLedger() else { ledger.submissions[index] = previous; return false }
        handoffChanged?(ledger.submissions[index]); publishQueue(); return true
    }
    func publishQueue() {
        guard let id = threadID else { return }
        let rows = ledger.submissions.filter { $0.thread == id && (["queued", "preparing", "sending", "unknown", "rejected"].contains($0.state) || ($0.state == "accepted" && $0.turn == nil)) }.map { item -> [String: Any] in
            ["id": item.id, "text": item.text, "state": item.state, "model": item.model, "effort": item.effort, "attachments": item.attachments.map { $0.name }, "error": item.error ?? "", "editable": item.state == "queued", "recoverable": item.queuedSubmission != nil && item.turn == nil && ["accepted", "unknown"].contains(item.state)]
        }
        emit("queue", ["items": rows, "paused": ledger.paused.contains(id)])
    }
    func publishAttachments() {
        emit("attachments", ["items": draftAttachments.map { item -> [String: Any] in
            var value: [String: Any] = ["id": item.id, "name": item.name, "mime": item.mime, "bytes": item.sourceBytes ?? item.data.count, "coverage": item.coverage ?? "legacy_inline", "hash": item.sourceHash ?? item.sha256]
            if item.mime.hasPrefix("image/") { value["preview"] = "data:" + item.mime + ";base64," + item.base64 }
            return value
        }])
    }
    static func inspectDirectory(_ path: String, isolated: Bool, requireEmpty: Bool = false) throws -> CodexDirectory {
        let url = URL(fileURLWithPath: path).standardizedFileURL
        guard path.hasPrefix("/"), let canonical = realpath(url.path, nil) else { throw CocoaError(.fileNoSuchFile) }
        let actual = String(cString: canonical); free(canonical)
        // The UI displays the resolved path. Subsequent validation rejects an
        // inode replacement, even if a new directory has the same spelling.
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        guard actual != "/", actual != home, actual != "/Users", actual != "/Applications",
              !actual.hasPrefix(home + "/Library/"), !actual.hasPrefix("/Applications/"),
              !URL(fileURLWithPath: actual).pathComponents.contains(where: { [".codex", ".aws", ".ssh"].contains($0) }) else { throw CocoaError(.fileReadNoPermission) }
        var info = stat()
        guard lstat(actual, &info) == 0, (info.st_mode & S_IFMT) == S_IFDIR,
              access(actual, R_OK | W_OK | X_OK) == 0 else { throw CocoaError(.fileWriteNoPermission) }
        if requireEmpty, !(try FileManager.default.contentsOfDirectory(atPath: actual)).isEmpty { throw CocoaError(.fileWriteFileExists) }
        return CodexDirectory(path: actual, device: UInt64(info.st_dev), inode: UInt64(info.st_ino), isolated: isolated)
    }
    func validBinding(_ binding: CodexBinding) -> Bool {
        guard let actual = try? Self.inspectDirectory(binding.directory.path, isolated: binding.directory.isolated), actual == binding.directory else {
            ledger.paused.insert(binding.thread); persistLedger(); publishQueue()
            notice("The working folder is missing, read-only, or has changed identity. Your draft is retained. Choose a new task and confirm its folder."); return false
        }
        return true
    }
    func chooseDirectory(create: Bool, isolated: Bool) {
        guard let window = web.window else { return }
        directoryChoiceGeneration += 1; let generation = directoryChoiceGeneration
        pendingDirectory = nil; emit("directoryCleared")
        // Both actions use the native folder selector. Existing empty folders
        // work directly; New Folder is available inside the same system sheet.
        let panel = NSOpenPanel(); panel.title = translate(create ? "Create or choose task folder" : "Choose task folder")
        panel.canChooseDirectories = true; panel.canChooseFiles = false
        panel.allowsMultipleSelection = false; panel.canCreateDirectories = true
        panel.message = translate(isolated ? "Independent task: choose an existing empty folder, or use New Folder. Selecting does not start a model." : "Existing project: contents are preserved. Confirm this exact directory before execution.")
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self = self, self.directoryChoiceGeneration == generation else { return }
            guard response == .OK, let url = panel.url else { self.pendingDirectory = nil; self.emit("directoryCleared"); return }
            do { self.previewDirectory(try Self.inspectDirectory(url.path, isolated: isolated, requireEmpty: isolated), create: false) }
            catch {
                self.pendingDirectory = nil; self.emit("directoryCleared")
                self.notice(Self.directoryError(error))
            }
        }
    }
    static func directoryError(_ error: Error) -> String {
        switch (error as NSError).code {
        case NSFileWriteFileExistsError: return "This folder is not empty. Select Existing project to preserve and use its contents, or choose an empty folder. No task was created."
        case NSFileNoSuchFileError: return "This folder no longer exists. Select an existing folder. No task was created."
        case NSFileReadNoPermissionError: return "This directory is outside the permitted task scope. Select a dedicated task folder. No task was created."
        default: return "This folder cannot be read and written, or its identity changed. Check its permissions and choose again. No task was created."
        }
    }
    func publishLanguage() {
        let catalog = (try? Data(contentsOf: resources.appendingPathComponent("project_first/native_i18n.json"))).flatMap { try? JSONSerialization.jsonObject(with: $0) } ?? [:]
        emit("locale", ["zh": translate("Back") != "Back", "catalog": catalog])
        controlState(); publishQueue(); publishAttachments(); publishDisplaySnapshot()
    }
    func previewDirectory(_ directory: CodexDirectory, create: Bool) {
        let token = UUID().uuidString
        pendingDirectory = (token, directory, create)
        emit("directory", ["token": token, "path": directory.path, "create": create, "isolated": directory.isolated,
            "scope": translate("Read and write this folder only. Sensitive configuration folders remain excluded. Business network access is disabled; model connection uses your existing login. No Git initialization.")])
    }
    func confirmDirectory(token: String, model: String, effort: String) {
        guard connected, !isBusy, !creatingThread, ledgerReadable, let pending = pendingDirectory, pending.token == token,
              validateModel(model, effort: effort, attachments: []) else { return }
        creatingThread = true
        let directory: CodexDirectory
        do {
            if pending.create {
                let url = URL(fileURLWithPath: pending.directory.path)
                let parent = try Self.inspectDirectory(url.deletingLastPathComponent().path, isolated: pending.directory.isolated)
                guard parent.device == pending.directory.device, parent.inode == pending.directory.inode else { throw CocoaError(.fileWriteNoPermission) }
                try FileManager.default.createDirectory(at: url, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
            }
            directory = try Self.inspectDirectory(pending.directory.path, isolated: pending.directory.isolated, requireEmpty: pending.directory.isolated)
            if !pending.create, directory != pending.directory { throw CocoaError(.fileWriteNoPermission) }
        } catch { creatingThread = false; pendingDirectory = nil; notice("Folder confirmation failed. No execution session was created. Review the folder again."); return }
        pendingDirectory = nil
        var params: [String: Any] = ["cwd": directory.path, "runtimeWorkspaceRoots": [directory.path], "permissions": "twos-integrated", "approvalPolicy": "on-request", "approvalsReviewer": "user", "model": model, "allowProviderModelFallback": false, "historyMode": "paginated", "environments": [["environmentId": "local", "cwd": directory.path, "runtimeWorkspaceRoots": [directory.path]]], "threadSource": "twos_confirmed_directory"]
        if !effort.isEmpty { params["config"] = ["model_reasoning_effort": effort] }
        request("thread/start", params) { [weak self] result in
            guard let self = self else { return }; self.creatingThread = false
            guard let result = result else {
                // request() already exposes the actual service error. Do not
                // overwrite it with a generic message that loses its details.
                self.emit("directoryCleared"); return
            }
            guard let thread = result["thread"] as? [String: Any], let id = thread["id"] as? String,
                  result["cwd"] as? String == directory.path, result["model"] as? String == model,
                  result["runtimeWorkspaceRoots"] as? [String] == [directory.path],
                  (result["activePermissionProfile"] as? [String: Any])?["id"] as? String == "twos-integrated",
                  thread["historyMode"] as? String == "paginated", thread["canAcceptDirectInput"] as? Bool == true else {
                let thread = result["thread"] as? [String: Any] ?? [:]
                let facts: [String: Any] = ["expectedCwd": directory.path, "returnedCwd": result["cwd"] ?? NSNull(), "threadId": thread["id"] ?? NSNull(),
                    "expectedModel": model, "returnedModel": result["model"] ?? NSNull(), "runtimeWorkspaceRoots": result["runtimeWorkspaceRoots"] ?? NSNull(),
                    "activePermissionProfile": result["activePermissionProfile"] ?? NSNull(), "historyMode": thread["historyMode"] ?? NSNull(), "canAcceptDirectInput": thread["canAcceptDirectInput"] ?? NSNull()]
                let detail = (try? JSONSerialization.data(withJSONObject: facts, options: [.prettyPrinted, .sortedKeys])).map { String(decoding: $0, as: UTF8.self) } ?? ""
                self.emit("directoryCleared")
                self.emit("notice", ["text": self.translate("Codex did not confirm the requested folder, permissions and model. No work was sent. Inspect the service response before creating another task."), "detail": detail]); return
            }
            let binding = CodexBinding(thread: id, directory: directory, permission: "twos-integrated", createdAt: Date().timeIntervalSince1970)
            self.ledger.bindings[id] = binding
            guard self.persistLedger() else { return }
            if self.threadID != nil { self.saveDraft(self.draftText) }
            self.displayItems.removeAll(); self.displayOrder.removeAll()
            self.selected = thread; self.loadedThread = id; self.controlledThreads.insert(id); self.historyReady = true; self.uncertain = false
            self.nextModel = model; self.nextEffort = effort; self.draftText = ""; self.sourceURL = nil
            self.saveDraft(""); self.emit("thread", ["thread": thread]); self.emitDraft(); self.emit("directoryConfirmed"); self.controlState(); self.publishQueue(); self.publishAttachments()
            self.request("thread/name/set", ["threadId": id, "name": URL(fileURLWithPath: directory.path).lastPathComponent]) { _ in self.listThreads() }
            if self.handoffCandidate != nil { self.showHandoff() }
        }
    }
    func validateModel(_ model: String, effort: String, attachments: [CodexAttachment]) -> Bool {
        guard let row = modelCatalog.first(where: { $0["model"] as? String == model }),
              effort.isEmpty || (row["supportedReasoningEfforts"] as? [[String: Any]] ?? []).contains(where: { $0["reasoningEffort"] as? String == effort }),
              !attachments.contains(where: { $0.mime.hasPrefix("image/") }) || (row["inputModalities"] as? [String] ?? []).contains("image") else {
            notice("Choose an available model and reasoning level that support these attachments. No model was substituted."); return false
        }
        return true
    }
    func importAttachment(name: String, mime: String, base64: String) {
        guard let target = threadID, let bytes = Data(base64Encoded: base64), !bytes.isEmpty else { notice(CodexAttachmentFailure.unreadable.message); return }
        let ext = URL(fileURLWithPath: name).pathExtension.lowercased()
        func accept(_ result: Result<CodexParsedAttachment, Error>) {
            emit("attachmentParsing", ["name": name, "parsing": false])
            switch result {
            case .failure(let error): emit("notice", ["text": translate((error as? CodexAttachmentFailure ?? .malformed).message), "detail": URL(fileURLWithPath: name).lastPathComponent])
            case .success(let parsed):
                let existing = ledger.drafts[target] ?? []
                guard existing.reduce(0, { $0 + ($1.sourceBytes ?? $1.data.count) }) + bytes.count <= 12_000_000 else { notice(CodexAttachmentFailure.tooLarge.message); return }
                let attachment = CodexAttachment(id: UUID().uuidString, name: URL(fileURLWithPath: name).lastPathComponent, mime: parsed.mime, base64: parsed.bytes.base64EncodedString(), transportVersion: parsed.mime.hasPrefix("image/") ? 3 : 2,
                    coverage: parsed.coverage, sourceBytes: parsed.sourceBytes, sourceHash: parsed.sourceHash)
                ledger.drafts[target, default: []].append(attachment)
                if persistLedger(), target == threadID { publishAttachments() }
            }
        }
        let scratch = preferences.appendingPathComponent("attachment-parser-temporary", isDirectory: true)
        if ["pdf", "docx", "xlsx", "pptx"].contains(ext) {
            emit("attachmentParsing", ["name": name, "parsing": true])
            DispatchQueue.global(qos: .userInitiated).async {
                let result = Result { try CodexAttachmentParser.parse(name: name, bytes: bytes, scratch: scratch) }
                DispatchQueue.main.async { accept(result) }
            }
        } else { accept(Result { try CodexAttachmentParser.parse(name: name, bytes: bytes, scratch: scratch) }) }
    }
    func chooseAttachments() {
        guard let window = web.window, let target = threadID else { return }
        let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.allowsMultipleSelection = true
        // Let the native chooser select a file; the bounded parser is the
        // authoritative format gate. Platform UTI registration varies (notably
        // code/Office files) and must not silently disable otherwise valid files.
        panel.allowedContentTypes = [.item]
        panel.message = translate("Choose explicit files only. They are read locally and sent only when you send the message.")
        panel.beginSheetModal(for: window) { [weak self] result in
            guard result == .OK, let self = self, self.threadID == target else { return }
            for url in panel.urls {
                guard let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize else {
                    self.emit("notice", ["text": self.translate(CodexAttachmentFailure.unreadable.message), "detail": url.lastPathComponent]); continue
                }
                guard size <= 8_000_000 else {
                    self.emit("notice", ["text": self.translate(CodexAttachmentFailure.tooLarge.message), "detail": url.lastPathComponent]); continue
                }
                guard let bytes = try? Data(contentsOf: url, options: .mappedIfSafe) else {
                    self.emit("notice", ["text": self.translate(CodexAttachmentFailure.unreadable.message), "detail": url.lastPathComponent]); continue
                }
                self.importAttachment(name: url.lastPathComponent, mime: "", base64: bytes.base64EncodedString())
            }
        }
    }
}

extension NativeCodex {
    func stage(_ text: String, source: URL, message: String = "") {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, text.utf8.count <= 200_000 else { notice("The instruction is empty or too large. Nothing was sent."); return }
        handoffCandidate = (text, source, message, Self.digest(Data(text.utf8)))
        if let id = threadID, let binding = ledger.bindings[id],
           let confirmed = ledger.handoffTargets?[source.absoluteString],
           confirmed.thread == id, confirmed.directory == binding.directory,
           confirmed.permission == binding.permission, canControl,
           draftAttachments.isEmpty {
            // The trusted website button is the explicit send action. Reuse
            // its confirmed target, while keeping every send-time scope,
            // writer-lease, model and duplicate check in confirmHandoff.
            confirmHandoff(model: nextModel, effort: nextEffort, hash: handoffCandidate!.hash)
            if handoffCandidate == nil { return }
        }
        showHandoff()
    }
    func showHandoff() {
        guard let candidate = handoffCandidate else { return }
        emit("handoff", ["text": candidate.text, "source": candidate.source.absoluteString, "message": candidate.message, "hash": candidate.hash,
                         "thread": threadID ?? "", "cwd": cwd ?? "", "canControl": canControl, "busy": isBusy,
                         "model": nextModel, "effort": nextEffort, "attachments": draftAttachments.map { $0.name }])
    }
    func confirmHandoff(model: String, effort: String, hash: String) {
        guard let candidate = handoffCandidate, candidate.hash == hash, let id = threadID, canControl else { return }
        if let prior = ledger.submissions.last(where: { $0.thread == id && $0.source == candidate.source.absoluteString && $0.message == candidate.message && $0.instructionHash == hash && !["cancelled", "rejected"].contains($0.state) }) {
            handoffCandidate = nil; handoffChanged?(prior); emit("handoffReceipt", ["id": prior.id, "state": prior.state]); return
        }
        guard let item = makeSubmission(text: candidate.text, model: model, effort: effort, mode: isBusy ? "queue" : "send", source: candidate.source.absoluteString, message: candidate.message, instructionHash: candidate.hash) else { return }
        let previousTargets = ledger.handoffTargets
        var targets = previousTargets ?? [:]
        targets[candidate.source.absoluteString] = ledger.bindings[id]
        ledger.handoffTargets = targets
        guard acceptSubmission(item) else { ledger.handoffTargets = previousTargets; return }
        handoffCandidate = nil; emit("handoffReceipt", ["id": item.id, "state": item.state]); handoffChanged?(item)
        if !isBusy { dispatchNext() }
    }
    func makeSubmission(text: String, model: String, effort: String, mode: String, source: String? = nil, message: String? = nil, instructionHash: String? = nil) -> CodexSubmission? {
        guard let id = threadID, let binding = ledger.bindings[id], binding.thread == id, binding.permission == "twos-integrated" else {
            notice("No confirmed task folder is available. Choose and confirm a task folder before sending; nothing was started."); return nil
        }
        guard cwd == binding.directory.path else {
            notice("The conversation folder differs from the confirmed target. Nothing was sent and neither folder was changed."); return nil
        }
        guard connected, historyReady, !uncertain, !submissionPending, ledgerReadable,
              !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !draftAttachments.isEmpty,
              text.utf8.count <= 200_000, validBinding(binding), validateModel(model, effort: effort, attachments: draftAttachments) else { return nil }
        return CodexSubmission(id: UUID().uuidString, thread: id, directory: binding.directory, text: text, attachments: draftAttachments, model: model, effort: effort, mode: mode, createdAt: Date().timeIntervalSince1970, source: source, message: message, instructionHash: instructionHash, state: "queued")
    }
    func retryHandoff(_ previousID: String, source: URL) {
        guard let prior = ledger.submissions.first(where: { $0.id == previousID }), prior.businessBlocked,
              prior.source == source.absoluteString, prior.thread == threadID else { return }
        // The original record is immutable. Repeated clicks on that record
        // resolve to its one child attempt, including after a restart.
        if let child = ledger.submissions.first(where: { $0.retryOf == previousID }) { handoffChanged?(child); return }
        guard draftAttachments.isEmpty, let binding = ledger.bindings[prior.thread], binding.directory == prior.directory else {
            notice("The retry target or attachments changed. Review the original task and its confirmed folder before sending."); return
        }
        // Do not turn an explicit retry into permission to drain older queued work.
        guard !ledger.submissions.contains(where: { $0.thread == prior.thread && !["completed", "failed", "interrupted", "cancelled", "rejected"].contains($0.state) }) else {
            notice("A delivery is still pending for this task. Inspect it before starting a new attempt."); return
        }
        guard var item = makeSubmission(text: prior.text, model: nextModel, effort: nextEffort, mode: "send", source: prior.source, message: prior.message, instructionHash: prior.instructionHash),
              validateModel(item.model, effort: item.effort, attachments: prior.attachments) else { return }
        item.attachments = prior.attachments; item.sourceContentHash = prior.sourceContentHash; item.retryOf = prior.id
        guard acceptSubmission(item) else { return }
        ledger.paused.remove(item.thread)
        guard persistLedger() else { ledger.paused.insert(item.thread); return }
        handoffChanged?(item); emit("handoffReceipt", ["id": item.id, "state": item.state]); dispatchNext()
    }
    func acceptSubmission(_ item: CodexSubmission) -> Bool {
        // A fresh explicit send may start after an earlier Stop when there is
        // no retained work left to resume. Never use that click to drain an
        // older queue or to resolve an ambiguous delivery implicitly.
        let wasPaused = ledger.paused.contains(item.thread)
        let hasRetainedInput = ledger.submissions.contains {
            $0.thread == item.thread && !["completed", "failed", "interrupted", "cancelled", "rejected"].contains($0.state)
        }
        if wasPaused && !hasRetainedInput && !isBusy && !uncertain { ledger.paused.remove(item.thread) }
        ledger.submissions.append(item)
        guard persistLedger() else {
            ledger.submissions.removeLast(); if wasPaused { ledger.paused.insert(item.thread) }; return false
        }
        publishQueue(); return true
    }
    func submitComposer(_ value: [String: Any]) {
        guard value["threadId"] as? String == nil || value["threadId"] as? String == threadID else { return }
        let mode = value["mode"] as? String ?? ledger.mode
        let current = isBusy && mode == "steer" ? ledger.submissions.first(where: { $0.id == activeSubmission }) : nil
        guard let item = makeSubmission(text: value["text"] as? String ?? "", model: current?.model ?? value["model"] as? String ?? nextModel,
                                        effort: current?.effort ?? value["effort"] as? String ?? nextEffort, mode: mode) else { return }
        if isBusy && item.mode == "steer", turnID == nil || ledger.submissions.first(where: { $0.id == activeSubmission })?.turn != turnID {
            notice("Wait for Codex to confirm the current input before steering this turn. Your draft is retained."); return
        }
        guard acceptSubmission(item) else { return }
        if isBusy && item.mode == "steer" { steer(item) }
        else {
            acknowledge(item)
            if !isBusy { dispatchNext() }
        }
    }
    func acknowledge(_ item: CodexSubmission) {
        // The user can type the next message while a request is awaiting its
        // receipt. Clear only the snapshot that was actually accepted.
        if draftText == item.text { saveDraft("") }
        if draftAttachments.map({ $0.id }) == item.attachments.map({ $0.id }) { ledger.drafts[item.thread] = []; persistLedger() }
        emit("sent", ["text": item.text, "id": item.id]); emitDraft(); publishAttachments(); controlState()
    }
    func steer(_ item: CodexSubmission) {
        guard let turn = turnID, item.thread == threadID, controlledThreads.contains(item.thread), !submissionPending else { return }
        submissionPending = true
        guard changeSubmission(item.id, { $0.state = "sending"; $0.turn = turn }) else { submissionPending = false; controlState(); return }
        controlState()
        request("turn/steer", ["threadId": item.thread, "expectedTurnId": turn, "clientUserMessageId": item.id, "input": item.input]) { [weak self] result in
            guard let self = self else { return }; self.submissionPending = false
            if result?["turnId"] as? String == turn {
                self.changeSubmission(item.id) { $0.state = self.completedTurns.contains(turn) ? "completed" : "accepted" }
                self.acknowledge(item)
                self.notice("The supplement was accepted for this turn. Codex may process it at its next safe boundary.")
            } else if let error = self.lastRequestFailure {
                self.changeSubmission(item.id) { $0.state = "rejected"; $0.error = error }
                self.notice("The supplement was not delivered to that turn. Your input is retained; send it as a new turn or queue it after reviewing the current state.")
            } else {
                self.changeSubmission(item.id) { $0.state = "unknown" }
                self.ledger.paused.insert(item.thread); self.uncertain = true; self.persistLedger()
                self.notice("Supplement receipt is unknown. Inspect the saved messages before retrying; it has not been resent.")
            }
            self.controlState()
        }
    }
    func scopeMatches(_ thread: [String: Any], binding: CodexBinding) -> Bool {
        guard thread["id"] as? String == binding.thread, thread["cwd"] as? String == binding.directory.path,
              thread["historyMode"] as? String == "paginated" else { return false }
        // Unloaded thread/read returns null environments in CLI 0.163. Loaded
        // scope is also checked against resume/start's effective roots/profile.
        if let environments = thread["environments"] as? [[String: Any]] {
            return environments.count == 1 && environments[0]["environmentId"] as? String == "local" &&
                environments[0]["cwd"] as? String == binding.directory.path &&
                environments[0]["runtimeWorkspaceRoots"] as? [String] == [binding.directory.path]
        }
        return thread["environments"] == nil || thread["environments"] is NSNull
    }
    func dispatchContext(_ item: CodexSubmission, binding: CodexBinding) -> String {
        // JSON quoting keeps even unusual folder names unambiguous. Only this
        // delivery's scope is included; no account or unrelated project data.
        let scope: [String: Any] = ["delivery_id": item.id, "thread_id": item.thread,
            "canonical_cwd": binding.directory.path, "allowed_write_root": binding.directory.path,
            "permission_profile": binding.permission, "directory_device": binding.directory.device,
            "directory_inode": binding.directory.inode, "confirmed_at": binding.createdAt,
            "verified_at": Date().timeIntervalSince1970, "retry_of": item.retryOf ?? "",
            "checks": ["saved_confirmation", "directory_identity_and_access", "thread_cwd", "effective_permission_profile_and_roots", "writer_lease", "empty_official_queue", "single_client_delivery_id"]]
        let json = String(data: try! JSONSerialization.data(withJSONObject: scope, options: [.sortedKeys, .withoutEscapingSlashes]), encoding: .utf8)!
        return """
        TWOS controller-verified execution context / 控制端已核验的本次执行上下文
        \(json)
        This context was generated by TWOS after native directory, permission, session and duplicate-dispatch checks. It does not grant additional tool rights.
        本次明确目标是 canonical_cwd。先用 pwd -P 核对实际 cwd 与它一致；不一致则停止。仅在 allowed_write_root 内按随后完整业务指令操作；不访问其他项目、认证资料，不扩大工具权限。敏感配置目录仍由沙盒排除，业务网络关闭。
        目录确认、内部任务绑定及是否重复派发由 TWOS 控制端负责，已经完成本次核验。若业务文字要求“读取右侧已确认目录/内部绑定”或“检查同一交付是否已执行”，使用以上上下文即可；执行器不需要也不应寻找内部绑定查询工具或其他会话。保留其余业务限制，核对真实 cwd 后继续执行。
        Report the actual business RESULT (PASS / PARTIAL / BLOCKED / FAIL), created files and tests actually run. A completed channel alone is not business success. Do not claim browser checks that were not performed.
        """
    }
    func ensureControl(_ completion: @escaping (Bool) -> Void) {
        guard let id = threadID, let binding = ledger.bindings[id], validBinding(binding) else { completion(false); return }
        if controlledThreads.contains(id) { completion(true); return }
        // Observe before resume: never rewrite a restored B session to target A.
        request("thread/read", ["threadId": id, "includeTurns": false]) { [weak self] read in
        guard let self = self else { completion(false); return }
        guard let existing = read?["thread"] as? [String: Any], self.scopeMatches(existing, binding: binding),
              ["idle", "notLoaded"].contains((existing["status"] as? [String: Any])?["type"] as? String ?? ""), self.threadID == id, self.validBinding(binding) else {
            self.notice("The saved conversation scope or idle state does not match this task. No resume or input was sent."); completion(false); return
        }
        // Paginated threads acquire a real app-server writer lease. A different
        // process already holding that lease rejects resume atomically.
        self.request("thread/resume", ["threadId": id, "excludeTurns": true, "cwd": binding.directory.path, "permissions": binding.permission,
                                  "runtimeWorkspaceRoots": [binding.directory.path], "approvalPolicy": "on-request", "approvalsReviewer": "user"]) { [weak self] result in
            guard let self = self else { completion(false); return }
            guard let result = result, let thread = result["thread"] as? [String: Any], thread["id"] as? String == id,
                  result["cwd"] as? String == binding.directory.path, result["runtimeWorkspaceRoots"] as? [String] == [binding.directory.path],
                  (result["activePermissionProfile"] as? [String: Any])?["id"] as? String == binding.permission,
                  thread["historyMode"] as? String == "paginated", thread["canAcceptDirectInput"] as? Bool == true,
                  (thread["status"] as? [String: Any])?["type"] as? String == "idle", self.threadID == id else {
                self.notice("This conversation is controlled elsewhere or its scope could not be verified. History remains readable; no work was started here."); completion(false); return
            }
            self.controlledThreads.insert(id); self.loadedThread = id; completion(true)
        }
        }
    }
    func dispatchNext() {
        guard connected, !isBusy, !submissionPending, !uncertain, let id = threadID, !ledger.paused.contains(id),
              let item = ledger.submissions.first(where: { $0.thread == id && $0.state == "queued" }),
              let binding = ledger.bindings[id], binding.thread == id, binding.permission == "twos-integrated", item.directory == binding.directory, validBinding(binding),
              validateModel(item.model, effort: item.effort, attachments: item.attachments) else { return }
        submissionPending = true; startingTurn = true; activeSubmission = item.id
        guard changeSubmission(item.id, { $0.state = "preparing" }) else { startingTurn = false; submissionPending = false; activeSubmission = nil; controlState(); return }
        controlState()
        ensureControl { [weak self] ok in
            guard let self = self else { return }
            guard ok, self.threadID == id else {
                self.startingTurn = false; self.submissionPending = false; self.activeSubmission = nil
                self.ledger.paused.insert(id); self.changeSubmission(item.id) { $0.state = "queued" }; self.controlState(); return
            }
            var settings: [String: Any] = ["threadId": id, "model": item.model, "summary": "auto"]
            if !item.effort.isEmpty { settings["effort"] = item.effort }
            self.request("thread/settings/update", settings) { result in
                guard result != nil, self.validBinding(binding) else {
                    self.startingTurn = false; self.submissionPending = false; self.ledger.paused.insert(id)
                    self.changeSubmission(item.id) { $0.state = "queued" }; self.controlState(); return
                }
                // Verify the effective model before handing one immutable input
                // to the official durable queue. No other queued input is
                // exposed to the service until a successful terminal event.
                self.request("thread/read", ["threadId": id, "includeTurns": false]) { verified in
                    guard let thread = verified?["thread"] as? [String: Any], self.scopeMatches(thread, binding: binding), self.threadID == id,
                          thread["model"] as? String == item.model,
                          item.effort.isEmpty || thread["reasoningEffort"] as? String == item.effort,
                          (thread["status"] as? [String: Any])?["type"] as? String == "idle" else {
                        self.startingTurn = false; self.submissionPending = false; self.ledger.paused.insert(id)
                        self.activeSubmission = nil
                        self.changeSubmission(item.id) { $0.state = "queued"; $0.error = "The task folder, next-turn settings or idle state could not be verified. Nothing was sent." }; self.controlState(); return
                    }
                    self.selected = thread
                    self.request("thread/queue/list", ["threadId": id]) { queue in
                        guard let entries = queue?["data"] as? [[String: Any]], entries.isEmpty else {
                            self.startingTurn = false; self.submissionPending = false; self.activeSubmission = nil; self.ledger.paused.insert(id)
                            self.changeSubmission(item.id) { $0.state = "queued"; $0.error = "An existing official queue entry needs control verification. Nothing was added." }
                            self.controlState(); return
                        }
                        guard self.threadID == id, self.ledger.bindings[id]?.directory == binding.directory, self.validBinding(binding) else {
                            self.startingTurn = false; self.submissionPending = false; self.activeSubmission = nil; self.ledger.paused.insert(id)
                            self.changeSubmission(item.id) { $0.state = "queued"; $0.error = "The confirmed folder changed before dispatch. Nothing was sent." }
                            self.controlState(); return
                        }
                    var dispatched = item
                    dispatched.dispatchContext = self.dispatchContext(item, binding: binding)
                    guard self.changeSubmission(item.id, { $0.state = "sending"; $0.error = nil; $0.dispatchContext = dispatched.dispatchContext }) else {
                        self.submissionPending = false; self.startingTurn = false; self.activeSubmission = nil; self.ledger.paused.insert(id); self.controlState(); return
                    }
                    self.pendingSource = item.source.flatMap(URL.init(string:)); self.candidateResult = ""
                    guard self.markPending("client:" + item.id), self.persistLedger() else { self.submissionPending = false; self.startingTurn = false; self.controlState(); return }
                    self.request("thread/queue/add", ["threadId": id, "clientUserMessageId": item.id, "input": dispatched.input]) { result in
                        self.submissionPending = false
                        if let entry = result?["queuedSubmission"] as? [String: Any], let qid = entry["id"] as? String, entry["clientUserMessageId"] as? String == item.id {
                            self.changeSubmission(item.id) { record in
                                record.queuedSubmission = qid
                                if record.state == "sending" { record.state = "accepted" }
                            }
                            self.acknowledge(item)
                            if self.turnID == nil, !self.completedTurns.contains(self.ledger.submissions.first(where: { $0.id == item.id })?.turn ?? "") { self.startAcceptedQueue(item.id) }
                        } else {
                            self.uncertain = true; self.ledger.paused.insert(id)
                            self.changeSubmission(item.id) { $0.state = "unknown"; $0.error = self.lastRequestFailure }
                            self.notice("Delivery receipt is unknown. This request will not be sent again; reconnect and inspect its recorded client ID.")
                        }
                        self.controlState()
                        if !self.isBusy && !self.uncertain { self.dispatchNext() }
                    }
                    }
                }
            }
        }
    }
    // Queue storage and starting a turn are separate protocol operations.
    // Interrupted/cold-resumed threads do not necessarily drain on queue/add.
    // Start only the exact persisted item after checking its original input;
    // never replace it with turn/start or enqueue it again on recovery.
    static func queueInputMatches(_ actual: [[String: Any]], _ expected: [[String: Any]]) -> Bool {
        func content(_ inputs: [[String: Any]]) -> [[String: String]]? {
            var result: [[String: String]] = []
            for input in inputs {
                guard let type = input["type"] as? String else { return nil }
                let key = type == "text" ? "text" : type == "image" ? "url" : ""
                guard !key.isEmpty, let value = input[key] as? String else { return nil }
                result.append(["type": type, key: value])
            }
            return result
        }
        guard let left = content(actual), let right = content(expected) else { return false }
        return left == right
    }
    func startAcceptedQueue(_ submissionID: String, recovering: Bool = false) {
        guard connected, !submissionPending, turnID == nil,
              let item = ledger.submissions.first(where: { $0.id == submissionID && $0.thread == threadID }),
              item.turn == nil, ["accepted", "unknown"].contains(item.state),
              let queueID = item.queuedSubmission,
              let binding = ledger.bindings[item.thread], binding.directory == item.directory,
              validBinding(binding), item.dispatchContext != nil,
              (recovering ? !isBusy : (!uncertain && activeSubmission == item.id)) else { return }
        submissionPending = true; startingTurn = true; activeSubmission = item.id
        controlState()
        func fail(_ reason: String) {
            guard self.threadID == item.thread, self.turnID == nil else { return }
            self.submissionPending = false; self.startingTurn = false; self.activeSubmission = nil
            self.uncertain = true; self.ledger.paused.insert(item.thread)
            self.changeSubmission(item.id) { $0.state = "unknown"; $0.error = reason }
            self.notice(reason); self.controlState()
        }
        func awaitStartedEvent() {
            self.submissionPending = false
            let generation = self.transportGeneration
            DispatchQueue.main.asyncAfter(deadline: .now() + 40) { [weak self = self] in
                guard let self = self, self.transportGeneration == generation,
                      self.activeSubmission == item.id, self.startingTurn, self.turnID == nil else { return }
                fail("Codex has not confirmed the queued turn start. Inspect delivery before continuing; the input was not resent.")
            }
            self.controlState()
        }
        ensureControl { [weak self] ok in
            guard let self = self else { return }
            guard ok else { fail("The saved queued input could not acquire this conversation's control. Nothing was resent."); return }
            self.request("thread/read", ["threadId": item.thread, "includeTurns": false]) { verified in
                // An automatic drain may have won the race. Its real events
                // already own the turn; never start an additional one.
                if self.turnID != nil || self.completedTurns.contains(self.ledger.submissions.first(where: { $0.id == item.id })?.turn ?? "") { self.submissionPending = false; self.controlState(); return }
                guard let thread = verified?["thread"] as? [String: Any], self.scopeMatches(thread, binding: binding),
                      thread["model"] as? String == item.model,
                      item.effort.isEmpty || thread["reasoningEffort"] as? String == item.effort,
                      self.threadID == item.thread, self.ledger.bindings[item.thread]?.directory == binding.directory,
                      self.validBinding(binding) else {
                    fail("The saved queue's folder, model or idle state could not be verified. No new turn was requested."); return
                }
                self.selected = thread
                let status = (thread["status"] as? [String: Any])?["type"] as? String
                if status == "active" {
                    // The automatic queue drain may update metadata before
                    // turn/started reaches this connection. Keep the exact
                    // pending input until userMessage.clientId identifies it;
                    // active metadata alone neither proves a foreign writer
                    // nor permits another queue/start.
                    awaitStartedEvent(); return
                }
                guard status == "idle" else {
                    fail("The saved queue's folder, model or idle state could not be verified. No new turn was requested."); return
                }
                self.request("thread/queue/list", ["threadId": item.thread]) { queue in
                    if self.turnID != nil || self.completedTurns.contains(self.ledger.submissions.first(where: { $0.id == item.id })?.turn ?? "") { self.submissionPending = false; self.controlState(); return }
                    guard let entries = queue?["data"] as? [[String: Any]], self.threadID == item.thread,
                          self.ledger.bindings[item.thread]?.directory == binding.directory, self.validBinding(binding) else {
                        fail("The exact saved queue entry could not be verified. Inspect delivery before continuing; nothing was resent."); return
                    }
                    // Consumption may precede the turn event even when the
                    // preceding metadata read still said idle. Absence is not
                    // proof of delivery; wait for the exact client ID.
                    if entries.isEmpty { awaitStartedEvent(); return }
                    guard entries.count == 1,
                          entries[0]["id"] as? String == queueID, entries[0]["clientUserMessageId"] as? String == item.id,
                          let input = entries[0]["input"] as? [[String: Any]], Self.queueInputMatches(input, item.input),
                          self.threadID == item.thread, self.ledger.bindings[item.thread]?.directory == item.directory, self.validBinding(binding) else {
                        fail("The exact saved queue entry could not be verified. Inspect delivery before continuing; nothing was resent."); return
                    }
                    self.uncertain = false; self.pendingSource = item.source.flatMap(URL.init(string:)); self.candidateResult = ""
                    guard self.markPending("client:" + item.id), self.changeSubmission(item.id, { $0.state = "accepted"; $0.error = nil }) else {
                        fail("The verified queue state could not be saved. Nothing was started."); return
                    }
                    self.request("thread/queue/start", ["threadId": item.thread, "queuedSubmissionId": queueID]) { result in
                        self.submissionPending = false
                        if let turn = result?["turn"] as? [String: Any], let turnID = turn["id"] as? String {
                            if !self.completedTurns.contains(turnID) {
                                self.turnID = turnID; self.startingTurn = false; self.bindOrigin(turnID); self.markPending(turnID)
                                self.changeSubmission(item.id) { $0.turn = turnID; $0.state = "running" }
                            }
                            self.ledger.paused.remove(item.thread); self.persistLedger(); self.controlState()
                        } else if self.turnID != nil || self.completedTurns.contains(self.ledger.submissions.first(where: { $0.id == item.id })?.turn ?? "") {
                            self.controlState() // An actual started/completed event won the race.
                        } else if self.lastRequestFailure != nil {
                            // A drain can also win after queue/list but before
                            // queue/start. Never enqueue or start again merely
                            // because that exact start was rejected.
                            awaitStartedEvent()
                        } else { fail("Codex has not confirmed the queued turn start. Inspect delivery before continuing; the input was not resent.") }
                    }
                }
            }
        }
    }
    func editQueue(_ value: [String: Any]) {
        guard let id = value["id"] as? String, let text = value["text"] as? String, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, text.utf8.count <= 200_000,
              let item = ledger.submissions.first(where: { $0.id == id && $0.thread == threadID }), item.state == "queued" else {
            notice("This input has already been dispatched or is a bound handoff. It was not edited."); return
        }
        guard let index = ledger.submissions.firstIndex(where: { $0.id == id }) else { return }
        var revised = CodexSubmission(id: UUID().uuidString, thread: item.thread, directory: item.directory, text: text, attachments: item.attachments, model: item.model, effort: item.effort, mode: item.mode, createdAt: Date().timeIntervalSince1970, source: item.source, message: item.message, instructionHash: item.source == nil ? nil : Self.digest(Data(text.utf8)), state: "queued")
        revised.sourceContentHash = item.sourceContentHash ?? item.instructionHash; revised.supersedes = id
        ledger.submissions[index].state = "cancelled"; ledger.submissions.insert(revised, at: index + 1)
        if persistLedger() { handoffChanged?(revised); publishQueue() }
    }
    func deleteQueue(_ id: String) {
        guard let item = ledger.submissions.first(where: { $0.id == id && $0.thread == threadID }), item.state == "queued" else {
            notice("This input has already been dispatched. Stop is a separate action; nothing was cancelled."); return
        }
        changeSubmission(id) { $0.state = "cancelled" }
    }
    func confirmedHistoryTerminal(_ turn: [String: Any]) -> String? {
        guard let tid = turn["id"] as? String else { return nil }
        let terminalStates = ["completed", "failed", "interrupted"]
        // A live event on this connection remains authoritative over a stale
        // observer projection. An unloaded reader can project an active turn
        // as interrupted with no completedAt, including turns/list responses.
        if completedTurns.contains(tid), let known = ledger.submissions.first(where: {
            $0.thread == threadID && $0.turn == tid && terminalStates.contains($0.state)
        }) { return known.state }
        guard let status = turn["status"] as? String, terminalStates.contains(status),
              let completed = turn["completedAt"] as? NSNumber, completed.doubleValue > 0,
              completed.doubleValue >= ((turn["startedAt"] as? NSNumber)?.doubleValue ?? 0) else { return nil }
        return status
    }
    func reconcileSavedInputs(_ turns: [[String: Any]]) {
        guard let id = threadID else { return }
        for turn in turns {
            guard let tid = turn["id"] as? String else { continue }
            let terminal = confirmedHistoryTerminal(turn)
            let items = turn["items"] as? [[String: Any]] ?? []
            let clients = Set(items.filter { $0["type"] as? String == "userMessage" }.compactMap { $0["clientId"] as? String })
            for index in ledger.submissions.indices where ledger.submissions[index].thread == id && clients.contains(ledger.submissions[index].id) {
                ledger.submissions[index].turn = tid
                ledger.submissions[index].state = terminal ?? (tid == turnID && controlledThreads.contains(id) ? "accepted" : "unknown")
                if terminal == "completed" {
                    ledger.submissions[index].result = items.last(where: { $0["type"] as? String == "agentMessage" && $0["phase"] as? String != "commentary" })?["text"] as? String
                }
                handoffChanged?(ledger.submissions[index])
            }
        }
        let unresolved = ledger.submissions.contains { $0.thread == id && ["preparing", "sending", "accepted", "running", "unknown"].contains($0.state) && !($0.turn == turnID && turnID != nil && controlledThreads.contains(id) && $0.state != "unknown") }
        if unresolved { uncertain = true }
        if !unresolved, readMap("codex-pending.json")[id]?.hasPrefix("client:") == true { clearPending() }
        persistLedger(); publishQueue(); controlState()
    }
    func reconcileDelivery() {
        guard let id = threadID, connected else { return }
        loadHistory(older: false)
        request("thread/queue/list", ["threadId": id]) { [weak self] result in
            guard let self = self, self.threadID == id else { return }
            for entry in result?["data"] as? [[String: Any]] ?? [] {
                guard let client = entry["clientUserMessageId"] as? String else { continue }
                self.changeSubmission(client) { $0.queuedSubmission = entry["id"] as? String; $0.state = "unknown"; $0.error = "Still present in the official queue; requires control verification before continuing." }
            }
        }
    }
}

// Display state is a projection of public service events, never a second
// execution engine. Official saved history remains the source after reconnect.
extension NativeCodex {
    func rememberDisplayItem(_ raw: [String: Any]) {
        guard let id = raw["id"] as? String, let type = raw["type"] as? String else { return }
        var item = raw
        if type == "reasoning" { item = ["id": id, "type": type, "summary": raw["summary"] ?? []] }
        if type == "hookPrompt" { return }
        if displayItems[id] == nil { displayOrder.append(id) }
        displayItems[id] = item
        if displayOrder.count > 400 { displayItems.removeValue(forKey: displayOrder.removeFirst()) }
    }
    func rememberDisplayEvent(_ method: String, _ p: [String: Any]) {
        if let item = p["item"] as? [String: Any] { rememberDisplayItem(item); return }
        let id = p["itemId"] as? String ?? ""
        if method == "turn/plan/updated" || method == "turn/diff/updated" {
            let turn = p["turnId"] as? String ?? ""
            if method == "turn/plan/updated" { rememberDisplayItem(["id": "plan-" + turn, "type": "plan", "steps": p["plan"] ?? [], "explanation": p["explanation"] ?? ""]) }
            else { rememberDisplayItem(["id": "diff-" + turn, "type": "fileChange", "changes": [["path": "", "diff": p["diff"] ?? ""]]]) }
            return
        }
        guard !id.isEmpty else { return }
        var item = displayItems[id] ?? ["id": id]
        if method == "item/agentMessage/delta" { item["type"] = "agentMessage"; item["text"] = (item["text"] as? String ?? "") + (p["delta"] as? String ?? "") }
        else if method == "item/reasoning/summaryTextDelta" {
            item["type"] = "reasoning"
            var parts = item["summary"] as? [String] ?? []
            let index = p["summaryIndex"] as? Int ?? 0
            guard index >= 0, index < 1000 else { return }
            while parts.count <= index { parts.append("") }
            parts[index] += p["delta"] as? String ?? ""; item["summary"] = parts
        } else if ["item/commandExecution/outputDelta", "item/fileChange/outputDelta"].contains(method) {
            item["type"] = method.contains("commandExecution") ? "commandExecution" : "fileChange"
            item["aggregatedOutput"] = (item["aggregatedOutput"] as? String ?? "") + (p["delta"] as? String ?? "")
        } else if method == "item/mcpToolCall/progress" { item["type"] = "mcpToolCall"; item["progress"] = p["message"] ?? "" }
        rememberDisplayItem(item)
    }
    func publishDisplaySnapshot() {
        emit("displaySnapshot", ["items": displayOrder.compactMap { displayItems[$0] }])
    }

    static let artifactTextTypes: Set<String> = ["html", "htm", "txt", "md", "json", "css", "js", "ts", "py", "swift", "csv", "svg", "log", "xml", "yaml", "yml"]
    static let artifactImageTypes: Set<String> = ["png", "jpg", "jpeg"]
    static func canonicalArtifactPath(_ path: String) -> String? {
        guard let pointer = realpath(path, nil) else { return nil }
        defer { free(pointer) }
        return String(cString: pointer)
    }
    static func artifactParts(_ raw: String, directory: CodexDirectory) throws -> [String] {
        let prefix = directory.path + "/"
        let relative = raw.hasPrefix(prefix) ? String(raw.dropFirst(prefix.count)) : raw
        let parts = relative.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
        guard !relative.hasPrefix("/"), !relative.contains("\0"), !parts.isEmpty,
              parts.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." && !$0.hasPrefix(".") }),
              artifactTextTypes.union(artifactImageTypes).contains(URL(fileURLWithPath: relative).pathExtension.lowercased()) else { throw CocoaError(.fileReadNoPermission) }
        return parts
    }
    // Walk from the confirmed directory handle, refusing symlink components.
    // A path spelling or a model-produced link never grants filesystem access.
    static func readArtifact(_ raw: String, directory: CodexDirectory) throws -> (URL, Data) {
        let parts = try artifactParts(raw, directory: directory)
        let root = Darwin.open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard root >= 0 else { throw CocoaError(.fileReadNoPermission) }
        defer { Darwin.close(root) }
        var rootInfo = stat()
        guard fstat(root, &rootInfo) == 0, UInt64(rootInfo.st_dev) == directory.device, UInt64(rootInfo.st_ino) == directory.inode,
              directory.path == Self.canonicalArtifactPath(directory.path) else { throw CocoaError(.fileReadNoPermission) }
        var current = root
        var opened: [Int32] = []
        defer { for fd in opened.reversed() { Darwin.close(fd) } }
        for (index, part) in parts.enumerated() {
            let fd = openat(current, part, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | (index < parts.count - 1 ? O_DIRECTORY : O_NONBLOCK))
            guard fd >= 0 else { throw CocoaError(.fileReadNoPermission) }
            opened.append(fd); current = fd
        }
        var info = stat()
        guard fstat(current, &info) == 0, (info.st_mode & S_IFMT) == S_IFREG, info.st_nlink == 1,
              info.st_size >= 0, info.st_size <= 8_000_000 else { throw CocoaError(.fileReadNoPermission) }
        let handle = FileHandle(fileDescriptor: current, closeOnDealloc: false)
        let bytes = try handle.readToEnd() ?? Data()
        var after = stat()
        guard fstat(current, &after) == 0, info.st_size == after.st_size, info.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec,
              info.st_mtimespec.tv_nsec == after.st_mtimespec.tv_nsec, bytes.count <= 8_000_000 else { throw CocoaError(.fileReadUnknown) }
        return (URL(fileURLWithPath: directory.path).appendingPathComponent(parts.joined(separator: "/")), bytes)
    }
    func listArtifacts(automatic: Bool = false) {
        guard let id = threadID, let binding = ledger.bindings[id], cwd == binding.directory.path, validBinding(binding) else { return }
        do {
            let root = URL(fileURLWithPath: binding.directory.path)
            let files = try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey], options: [.skipsHiddenFiles])
            let rows = files.sorted { $0.lastPathComponent < $1.lastPathComponent }.prefix(250).compactMap { url -> [String: Any]? in
                guard (try? Self.artifactParts(url.lastPathComponent, directory: binding.directory)) != nil,
                      let values = try? url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]),
                      values.isRegularFile == true, values.isSymbolicLink != true else { return nil }
                return ["path": url.lastPathComponent, "bytes": values.fileSize ?? 0, "html": ["html", "htm"].contains(url.pathExtension.lowercased())]
            }
            emit("artifacts", ["threadId": id, "cwd": binding.directory.path, "items": rows, "limited": files.count > 250, "automatic": automatic])
        } catch { if !automatic { notice("Files could not be listed. The confirmed folder and saved work have not been changed.") } }
    }
    // Only the native save panel supplies the destination. The renderer never
    // supplies an output path, and saving a copy does not send a model request.
    static func saveArtifactCopy(_ path: String, directory: CodexDirectory, expectedHash: String, to destination: URL) throws {
        let (source, bytes) = try readArtifact(path, directory: directory)
        guard digest(bytes) == expectedHash, destination.isFileURL else { throw CocoaError(.fileWriteNoPermission) }
        let parent = destination.deletingLastPathComponent()
        let name = destination.lastPathComponent
        guard !name.isEmpty, name != ".", name != "..",
              let canonical = canonicalArtifactPath(parent.path),
              parent.path == canonical,
              destination.standardizedFileURL.path != source.path else { throw CocoaError(.fileWriteNoPermission) }
        let fd = Darwin.open(canonical, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard fd >= 0 else { throw CocoaError(.fileWriteNoPermission) }
        defer { Darwin.close(fd) }
        var parentInfo = stat(), actualParent = stat(), target = stat(), sourceInfo = stat()
        guard fstat(fd, &parentInfo) == 0, lstat(canonical, &actualParent) == 0,
              parentInfo.st_dev == actualParent.st_dev, parentInfo.st_ino == actualParent.st_ino,
              lstat(source.path, &sourceInfo) == 0 else { throw CocoaError(.fileWriteNoPermission) }
        let existing = fstatat(fd, name, &target, AT_SYMLINK_NOFOLLOW)
        guard (existing == 0 && (target.st_mode & S_IFMT) == S_IFREG && target.st_nlink == 1)
                || (existing != 0 && errno == ENOENT) else { throw CocoaError(.fileWriteNoPermission) }
        guard existing != 0 || target.st_dev != sourceInfo.st_dev || target.st_ino != sourceInfo.st_ino else { throw CocoaError(.fileWriteNoPermission) }
        let temporary = ".twos-export-" + UUID().uuidString
        let output = openat(fd, temporary, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
        guard output >= 0 else { throw CocoaError(.fileWriteUnknown) }
        defer { Darwin.close(output); unlinkat(fd, temporary, 0) }
        let handle = FileHandle(fileDescriptor: output, closeOnDealloc: false)
        try handle.write(contentsOf: bytes)
        try handle.synchronize()
        // Use the same directory handle for the atomic replacement: a swapped
        // destination symlink cannot redirect the write into another directory.
        guard lstat(canonical, &actualParent) == 0,
              parentInfo.st_dev == actualParent.st_dev, parentInfo.st_ino == actualParent.st_ino,
              renameat(fd, temporary, fd, name) == 0 else { throw CocoaError(.fileWriteUnknown) }
    }
    func saveArtifact(_ path: String, binding: CodexBinding, source: URL, bytes: Data) {
        guard artifactSavePanel == nil, let window = web.window else { return }
        let id = binding.thread, generation = selectionGeneration
        let panel = NSSavePanel()
        panel.title = translate("Save artifact as")
        panel.message = translate("Save a copy of this file. The original remains in the task folder.")
        panel.nameFieldStringValue = source.lastPathComponent
        panel.canCreateDirectories = true
        if let type = UTType(filenameExtension: source.pathExtension) { panel.allowedContentTypes = [type] }
        panel.allowsOtherFileTypes = false
        artifactSavePanel = panel
        panel.beginSheetModal(for: window) { [weak self] response in
            guard let self = self else { return }
            defer { self.artifactSavePanel = nil }
            guard response == .OK, let destination = panel.url else { return }
            guard self.threadID == id, self.selectionGeneration == generation,
                  let current = self.ledger.bindings[id], current.directory == binding.directory,
                  current.permission == binding.permission, current.createdAt == binding.createdAt,
                  self.cwd == binding.directory.path,
                  self.validBinding(current) else {
                self.notice("The task or folder changed while choosing a save location. Nothing was exported."); return
            }
            do {
                try Self.saveArtifactCopy(path, directory: binding.directory, expectedHash: Self.digest(bytes), to: destination)
                self.emit("artifactSaved", ["threadId": id, "path": source.path, "destination": destination.path])
            } catch {
                self.notice("The copy could not be saved. The source may have changed, or the destination is unavailable, linked, or the original file. Choose another location and try again.")
            }
        }
    }
    func artifactAction(_ value: [String: Any]) {
        guard let id = threadID, value["threadId"] as? String == id, let binding = ledger.bindings[id],
              cwd == binding.directory.path, validBinding(binding), let path = value["path"] as? String,
              let action = value["operation"] as? String, ["view", "reveal", "browser", "save"].contains(action) else { return }
        do {
            let (url, data) = try Self.readArtifact(path, directory: binding.directory)
            if action == "save" {
                saveArtifact(path, binding: binding, source: url, bytes: data)
            } else if action == "view" {
                if Self.artifactImageTypes.contains(url.pathExtension.lowercased()), NSBitmapImageRep(data: data) != nil {
                    emit("artifactContent", ["threadId": id, "path": url.path, "image": "data:image/" + (url.pathExtension.lowercased() == "png" ? "png" : "jpeg") + ";base64," + data.base64EncodedString()])
                } else if data.count <= 2_000_000, let text = String(data: data, encoding: .utf8) {
                    // Text only. Even HTML is never loaded in the bridge view.
                    emit("artifactContent", ["threadId": id, "path": url.path, "text": text])
                } else { notice("This file is not a supported UTF-8 text or image preview, or exceeds the preview size limit.") }
            } else {
                // Recheck immediately before passing an actual, in-scope URL
                // to LaunchServices; no shell and no broad filesystem grant.
                guard Self.canonicalArtifactPath(url.path) == url.path, validBinding(binding) else { throw CocoaError(.fileReadNoPermission) }
                if action == "reveal" { NSWorkspace.shared.activateFileViewerSelecting([url]); return }
                guard ["html", "htm"].contains(url.pathExtension.lowercased()),
                      let safari = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Safari") else {
                    notice("Safari could not be located by the host. The file was not executed; use Show in Finder to inspect it."); return
                }
                let config = NSWorkspace.OpenConfiguration(); config.activates = true
                NSWorkspace.shared.open([url], withApplicationAt: safari, configuration: config) { [weak self] _, error in
                    DispatchQueue.main.async {
                        guard let self = self, self.threadID == id else { return }
                        self.emit("artifactOpened", ["path": url.path, "opened": error == nil, "error": error?.localizedDescription ?? ""])
                    }
                }
            }
        } catch { notice("This file is missing, outside the confirmed folder, linked elsewhere, changed during reading, or not supported. Nothing was opened.") }
    }
}
