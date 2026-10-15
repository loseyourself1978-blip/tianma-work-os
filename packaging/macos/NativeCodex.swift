import AppKit
import WebKit
import Darwin

// One native-owned connection; only the bundled local renderer can call it.
// Remote website panes never receive this script-message handler.
final class NativeCodex: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
    let web: WKWebView
    let resources: URL
    let preferences: URL
    let translate: (String) -> String
    var returnResult: ((String, URL) -> Void)?
    var process: Process?
    var input: Pipe?
    var output: Pipe?
    var errors: Pipe?
    var diagnosticTail = ""
    var buffer = Data()
    var requestID = 0
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
    var historyCursor: String?
    var sourceURL: URL?
    var lastResult = ""
    var connected = false
    var pageReady = false
    var pendingUI: [[String: Any]] = []
    var modelIDs = Set<String>()
    var ownerDesktopRunning: () -> Bool = { !NSRunningApplication.runningApplications(withBundleIdentifier: "com.openai.codex").isEmpty }
    var isBusy: Bool { startingTurn || turnID != nil }
    var threadID: String? { selected?["id"] as? String }
    var cwd: String? { selected?["cwd"] as? String }

    init(resources: URL, preferences: URL, translate: @escaping (String) -> String) {
        self.resources = resources; self.preferences = preferences; self.translate = translate
        let config = WKWebViewConfiguration(); config.websiteDataStore = .nonPersistent()
        web = WKWebView(frame: .zero, configuration: config)
        super.init()
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
        emit("control", ["connected": connected, "busy": isBusy, "desktopRunning": ownerDesktopRunning(), "threadId": threadID ?? "", "uncertain": uncertain, "historyReady": historyReady])
    }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame,
              message.frameInfo.request.url?.standardizedFileURL == resources.appendingPathComponent("native_codex/index.html").standardizedFileURL,
              let value = message.body as? [String: Any], let action = value["action"] as? String else { return }
        switch action {
        case "ready":
            pageReady = true
            let queued = pendingUI; pendingUI = []
            for event in queued { emit(event["kind"] as! String, event["payload"] as? [String: Any] ?? [:]) }
            emit("locale", ["zh": translate("Back") != "Back"]); controlState(); restoreDraft()
        case "connect": connect()
        case "reconnect":
            guard uncertain || !isBusy else { return }
            reconnect()
        case "refresh": if connected && !isBusy { listThreads(); if let id = threadID { selectThread(id) } }; controlState()
        case "moreThreads": listThreads(older: true)
        case "select": if let id = value["id"] as? String { selectThread(id) }
        case "send": if let text = value["text"] as? String { sendTurn(text, model: value["model"] as? String) }
        case "interrupt": interrupt()
        case "workspace":
            if let cwd = cwd, FileManager.default.fileExists(atPath: cwd) { NSWorkspace.shared.selectFile(nil, inFileViewerRootedAtPath: cwd) }
        case "answer": answer(value)
        case "draft":
            if let text = value["text"] as? String, text.utf8.count <= 200_000 { saveDraft(text) }
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
    func stage(_ text: String, source: URL) {
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
        emit("result", ["available": !lastResult.isEmpty && resultSource != nil, "source": resultSource?.absoluteString ?? ""])
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
        let paths = ["/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex", "/Applications/Codex.app/Contents/Resources/codex"]
        guard let path = paths.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            notice("The installed Codex command could not be found. Install the official Codex App first."); return
        }
        let child = Process(); child.executableURL = URL(fileURLWithPath: path)
        // This profile is passed only to this process. User config is not edited.
        // It excludes unrelated user files; runtime roots are bound at resume.
        child.arguments = ["app-server", "--listen", "stdio://", "-c", "features.multi_agent=false", "-c", "features.apps=false", "-c", "features.plugins=false", "-c", "mcp_servers={}", "-c", "web_search=\"disabled\"", "-c", "allow_login_shell=false", "-c", "shell_environment_policy.inherit=\"core\"",
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
                let unresolved = self.isBusy || self.uncertain
                self.uncertain = unresolved; self.releaseLock()
                self.turnID = nil; self.startingTurn = false; self.loadedThread = nil
                self.callbacks.removeAll(); self.approvals.removeAll(); self.controlState()
                self.emit("clearApprovals")
                self.notice(unresolved ? "Codex disconnected during execution. The request will not be sent again automatically. Reconnect and inspect the saved conversation." : "Codex disconnected. Reconnect to view your saved conversations.")
                if !self.diagnosticTail.isEmpty && ended.terminationStatus != 0 {
                    self.emit("notice", ["text": self.translate("The local Codex service stopped. Expand the details for its reported cause."), "detail": self.diagnosticTail])
                }
            }
        }
        process = child
        do { try child.run() } catch { notice("Codex could not start. Your saved conversations have not been changed."); return }
        request("initialize", ["clientInfo": ["name": "twos_integrated_workbench", "title": "Tianma Work OS", "version": "1.0.1"], "capabilities": ["experimentalApi": true]]) { [weak self] result in
            guard let self = self else { return }
            guard result != nil else { self.disconnect(); return }
            self.write(["method": "initialized"]); self.connected = true; self.controlState(); self.listThreads()
            if let id = self.threadID ?? self.restoringThread { self.selectThread(id) }
            self.request("model/list", ["limit": 100]) { result in
                let models = result?["data"] as? [[String: Any]] ?? []
                self.modelIDs = Set(models.compactMap { $0["model"] as? String })
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
        requestID += 1; let id = requestID; let generation = transportGeneration; callbacks[id] = completion
        write(["id": id, "method": method, "params": params])
        DispatchQueue.main.asyncAfter(deadline: .now() + 40) { [weak self] in
            guard let self = self, self.transportGeneration == generation, let callback = self.callbacks.removeValue(forKey: id) else { return }
            self.notice("Codex has not confirmed this request. Do not resend it until the conversation has been checked.")
            callback(nil)
        }
    }
    func receive(_ bytes: Data) {
        buffer.append(bytes)
        guard buffer.count <= 16_000_000 else { notice("A Codex event was too large to display. The saved conversation remains available."); disconnect(); return }
        while let index = buffer.firstIndex(of: 10) {
            let line = Data(buffer[..<index]); buffer.removeSubrange(...index)
            guard let value = try? JSONSerialization.jsonObject(with: line) as? [String: Any] else { continue }
            if value["method"] == nil, let id = value["id"] as? Int, let callback = callbacks.removeValue(forKey: id) {
                if let error = value["error"] as? [String: Any] {
                    emit("notice", ["text": translate("The local Codex service rejected this request. Saved work is retained."), "code": error["code"] as? Int ?? -1, "detail": error["message"] as? String ?? ""])
                    callback(nil)
                } else { callback(value["result"] as? [String: Any] ?? [:]) }
                continue
            }
            guard let method = value["method"] as? String, let params = value["params"] as? [String: Any] else { continue }
            let target = params["threadId"] as? String
            if let id = value["id"] {
                guard target == threadID, let turn = params["turnId"] as? String, turn == turnID,
                      ["item/commandExecution/requestApproval", "item/fileChange/requestApproval", "item/permissions/requestApproval", "item/tool/requestUserInput"].contains(method) else {
                    write(["id": id, "error": ["code": -32601, "message": "Request not supported by this client"]]); continue
                }
                let key = UUID().uuidString
                approvals[key] = ["id": id, "method": method, "params": params]
                emit("approval", ["key": key, "method": method, "params": params]); continue
            }
            guard target == threadID else { continue }
            if method == "turn/started", let turn = params["turn"] as? [String: Any], let id = turn["id"] as? String, startingTurn || turnID == id {
                if !completedTurns.contains(id) { turnID = id; startingTurn = false; bindOrigin(id); markPending(id); controlState() }
            }
            if method == "turn/completed", let turn = params["turn"] as? [String: Any], let id = turn["id"] as? String, id == turnID || startingTurn {
                completedTurns.insert(id); bindOrigin(id)
                if turn["status"] as? String == "completed" {
                    lastResult = candidateResult
                    resultSource = readMap("codex-return-origins.json")[((threadID ?? "") + "/" + id)].flatMap(URL.init(string:))
                }
                lastHistoryTurn = id; turnID = nil; startingTurn = false; approvals.removeAll(); clearPending(); releaseLock(); controlState(); publishResult()
                emit("turnCompleted", ["status": turn["status"] ?? "unknown", "error": turn["error"] ?? NSNull()]); continue
            }
            if let eventTurn = params["turnId"] as? String, eventTurn != turnID { continue }
            if method == "item/started" || method == "item/completed", let item = params["item"] as? [String: Any] {
                if item["type"] as? String == "reasoning" {
                    emit("summary", ["id": item["id"] ?? "", "summary": item["summary"] ?? []]); continue
                }
                if method == "item/completed", item["type"] as? String == "agentMessage", let text = item["text"] as? String {
                    if item["phase"] as? String != "commentary" { candidateResult = text }
                }
            }
            if method.hasPrefix("item/reasoning/") && method != "item/reasoning/summaryTextDelta" { continue }
            if ["item/started", "item/completed", "item/agentMessage/delta", "item/commandExecution/outputDelta", "item/fileChange/outputDelta", "item/reasoning/summaryTextDelta", "turn/plan/updated", "turn/diff/updated", "error", "serverRequest/resolved"].contains(method) {
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
        guard connected, !isBusy, UUID(uuidString: id) != nil else { return }
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
            self.selected = thread; self.lastResult = ""; self.resultSource = nil; self.historyCursor = nil; self.historyLoading = false; self.historyReady = false
            self.uncertain = self.readMap("codex-pending.json")[id] != nil
            self.saveDraft(self.draftText)
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
                       ["completed", "interrupted", "failed"].contains(turn["status"] as? String ?? ""),
                       !pending.hasPrefix("unconfirmed:") || tid != String(pending.dropFirst(12)) { self.clearPending() }
                }
                self.historyReady = true
                if self.uncertain { self.notice("The last execution has no confirmed final state. Inspect its history; TWOS will not repeat it.") }
                self.controlState()
            }
            if self.lastResult.isEmpty {
                let origins = self.readMap("codex-return-origins.json")
                for turn in turns where turn["status"] as? String == "completed" {
                    guard let tid = turn["id"] as? String, let source = origins[id + "/" + tid].flatMap(URL.init(string:)) else { continue }
                    let items = turn["items"] as? [[String: Any]] ?? []
                    if let item = items.last(where: { $0["type"] as? String == "agentMessage" && $0["phase"] as? String != "commentary" }), let text = item["text"] as? String, !text.isEmpty {
                        self.lastResult = text; self.resultSource = source; break
                    }
                }
            }
            self.emit("history", ["turns": turns, "older": older, "more": self.historyCursor != nil]); self.publishResult()
        }
    }
    func sendTurn(_ raw: String, model: String?) {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard connected, historyReady, !isBusy, !uncertain, !text.isEmpty, text.utf8.count <= 200_000,
              let id = threadID, let cwd = cwd, FileManager.default.fileExists(atPath: cwd) else { return }
        // A separate desktop process cannot expose authoritative active state to
        // this transport. Existing threads are view-only while it is running.
        guard !ownerDesktopRunning() else { notice("To continue this existing conversation here, quit the Codex App first. Its history and project stay intact; TWOS will use the same conversation ID."); controlState(); return }
        guard model == nil || model == "" || modelIDs.contains(model!) else { notice("Choose a model advertised by the connected Codex service."); return }
        guard acquireLock(id) else { notice("Another TWOS connection is using this conversation. Wait for it to finish."); return }
        guard markPending() else { releaseLock(); return }
        startingTurn = true; pendingSource = sourceURL; candidateResult = ""; controlState(); lastResult = ""; resultSource = nil; publishResult()
        request("thread/resume", ["threadId": id, "excludeTurns": true, "permissions": "twos-integrated", "runtimeWorkspaceRoots": [cwd], "approvalPolicy": "on-request", "approvalsReviewer": "user"]) { [weak self] result in
            guard let self = self else { return }
            guard let thread = result?["thread"] as? [String: Any], thread["id"] as? String == id,
                  (result?["cwd"] as? String ?? thread["cwd"] as? String) == cwd,
                  (thread["status"] as? [String: Any])?["type"] as? String != "active", !self.ownerDesktopRunning() else {
                self.startingTurn = false; self.clearPending(); self.releaseLock(); self.controlState(); return
            }
            self.loadedThread = id
            var params: [String: Any] = ["threadId": id, "input": [["type": "text", "text": text]],
                "permissions": "twos-integrated", "runtimeWorkspaceRoots": [cwd], "cwd": cwd,
                "approvalPolicy": "on-request", "approvalsReviewer": "user", "summary": "auto"]
            if let model = model, !model.isEmpty { params["model"] = model }
            self.request("turn/start", params) { result in
                guard let turn = result?["turn"] as? [String: Any], let turnID = turn["id"] as? String else {
                    // Outcome may be unknown. Stay blocked until an explicit
                    // reconnect/history inspection; never auto-submit again.
                    self.uncertain = true; self.controlState(); self.notice("Execution was not confirmed. Reconnect and inspect the conversation before trying again."); return
                }
                self.bindOrigin(turnID)
                if !self.completedTurns.contains(turnID) { self.turnID = turnID; self.markPending(turnID) }
                self.startingTurn = false
                self.saveDraft(""); self.emit("sent", ["text": text]); self.controlState()
            }
        }
    }
    func interrupt() {
        guard let id = threadID, let turn = turnID else { return }
        request("turn/interrupt", ["threadId": id, "turnId": turn]) { _ in }
    }
    func answer(_ value: [String: Any]) {
        guard let key = value["key"] as? String, let request = approvals.removeValue(forKey: key),
              let params = request["params"] as? [String: Any], params["threadId"] as? String == threadID,
              params["turnId"] as? String == turnID, let method = request["method"] as? String, let id = request["id"] else { return }
        var result: [String: Any] = [:]
        if method == "item/tool/requestUserInput", let responses = value["answers"] as? [String: [String]] {
            let questions = params["questions"] as? [[String: Any]] ?? []
            result["answers"] = Dictionary(uniqueKeysWithValues: questions.compactMap { question -> (String, [String: [String]])? in
                guard let name = question["id"] as? String else { return nil }
                return (name, ["answers": responses[name] ?? []])
            })
        } else if method == "item/permissions/requestApproval" {
            // Scope expansion is not silently accepted by this integration.
            result = ["permissions": [:], "scope": "turn"]
        } else { result = ["decision": value["accept"] as? Bool == true ? "accept" : "decline"] }
        write(["id": id, "result": result]); emit("answered", ["key": key])
    }
    func disconnect() {
        if isBusy { interrupt() }
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
