import Foundation

// Metadata only: no prompts, file contents, hidden reasoning, or credentials.
// A cumulative service snapshot is replaced, never summed with its predecessor.
struct CodexTokenSnapshot: Codable {
    var turn: String
    var total: [String: Int]
    var last: [String: Int]
    var updated: Double
}
struct CodexRunObservation: Codable {
    var thread: String
    var turn: String
    var started: Double?
    var ended: Double?
    var serviceDuration: Double?
    var lastActivity: Double
    var state = "running"
    var activeSeconds = 0.0
    var observedElapsed = 0.0
    var waitSeconds = 0.0
    var offlineUnknown = false
    var tools: Set<String> = []
    var activeTools: Set<String> = []
    var requests: [String: String] = [:]
    var plan: [String: String] = [:]
    var planRevisions = 0
    var stepStarts: [String: Double] = [:]
    var stepSamples: [Double] = []
    var observedPlanCompletions: Set<String> = []
    var requestedModel: String?
    var returnedModel: String?
    var serviceInterrupted: Bool? = nil
    var terminal: Bool { ["completed", "failed", "interrupted", "cancelled"].contains(state) }
    func wallTimes(submitted: Double?, now: Double) -> [String: Any] {
        // Wall timestamps are separate from monotonic observed execution time.
        // A terminal record without an end timestamp must not keep counting.
        let end = terminal ? ended : now
        return ["sinceSubmission": submitted.flatMap { begin in end.map { max(0, $0 - begin) } } as Any? ?? NSNull(),
                "beforeStart": submitted.flatMap { begin in started.map { max(0, $0 - begin) } } as Any? ?? NSNull()]
    }
    mutating func planUpdate(_ steps: [[String: Any]]) {
        var next: [String: String] = [:]
        for (i, step) in steps.enumerated() {
            let key = NativeCodex.digest(Data("\(i):\(step["step"] as? String ?? "")".utf8))
            let status = step["status"] as? String ?? "unknown"; next[key] = status
            // Reopened work is new work, not the old completion/sample again.
            if plan[key] == "completed", status != "completed" {
                observedPlanCompletions.remove(key); stepStarts.removeValue(forKey: key)
            }
            if status == "inProgress", stepStarts[key] == nil { stepStarts[key] = activeSeconds }
            if status == "completed", observedPlanCompletions.insert(key).inserted, let begin = stepStarts[key] {
                let duration = activeSeconds - begin
                if duration >= 1 { stepSamples.append(duration); stepSamples = Array(stepSamples.suffix(30)) }
            }
        }
        if Set(next.keys) != Set(plan.keys) || next.contains(where: { plan[$0.key] == "completed" && $0.value != "completed" }) { planRevisions += 1 }
        plan = next
        stepStarts = stepStarts.filter { next[$0.key] != nil }
    }
    func workload(now: Double, online: Bool) -> [String: Any] {
        // Public protocol exposes step/status, not weights or partial quantities.
        // Equal steps are a work-item estimate, never a time completion ratio.
        let done = plan.values.filter { $0 == "completed" }.count
        let valid = !plan.isEmpty && plan.values.allSatisfy { ["pending", "inProgress", "completed"].contains($0) }
        let stale = !terminal && (!online || state == "unverified" || serviceInterrupted == true || now - lastActivity > 180)
        var result: [String: Any] = ["available": valid || state == "completed", "scope": "current_turn_execution",
            "basis": state == "completed" ? "execution_ended" : "equal_plan_items", "planVersion": planRevisions,
            "done": done, "total": plan.count, "updated": lastActivity, "stale": stale,
            "reason": plan.isEmpty ? "no_plan" : "invalid_plan_status"]
        if state == "completed" { result["remainingPercent"] = 0.0 }
        else if valid { result["remainingPercent"] = 100 * Double(plan.count - done) / Double(plan.count) }
        return result
    }
    // Estimates use observed durations of completed steps in this run only.
    // This intentionally excludes parallel child durations and offline intervals.
    func estimate(now: Double, online: Bool) -> [String: Any] {
        let remaining = plan.values.filter { $0 != "completed" }.count
        let reason: String
        if terminal { reason = "terminal" }
        else if !online || serviceInterrupted == true || offlineUnknown && state == "unverified" { reason = "offline" }
        else if !requests.isEmpty { reason = "waiting_user" }
        else if now - lastActivity > 180 { reason = "stale_activity" }
        else if plan.isEmpty || remaining == 0 { reason = "unknown_remaining_work" }
        else if !plan.values.allSatisfy({ ["pending", "inProgress", "completed"].contains($0) }) { reason = "invalid_plan_status" }
        else if stepSamples.count < 2 { reason = "insufficient_samples" }
        else if stepSamples.min()! <= 0 || stepSamples.max()! > stepSamples.min()! * 3 { reason = "heterogeneous_samples" }
        else {
            let sorted = stepSamples.sorted(), mid = sorted[sorted.count / 2]
            let currentAge = stepStarts.filter { plan[$0.key] == "inProgress" }.map { max(0, activeSeconds - $0.value) }.max() ?? 0
            let overrun = currentAge > sorted.last! * 1.5
            let perStep = max(mid, overrun ? currentAge : 0)
            return ["available": true, "low": max(1, perStep * Double(remaining) * 0.6), "high": max(2, max(perStep, sorted.last!) * Double(remaining) * 1.8),
                    "samples": sorted.count, "confidence": sorted.count >= 5 ? "moderate" : "low", "updated": lastActivity,
                    "basis": "observed_plan_step_durations", "reassessed": overrun]
        }
        return ["available": false, "reason": reason, "samples": stepSamples.count]
    }
}
struct CodexTelemetryStore: Codable {
    var runs: [String: CodexRunObservation] = [:]
    var tokens: [String: CodexTokenSnapshot] = [:]
    var accountIdentity: String?
    var authentication: String?
    var plan: String?
    var limits: Data?
    var usage: Data?
    var limitsUpdated: Double?
    var usageUpdated: Double?
}

extension NativeCodex {
    func restoreTelemetry() {
        let file = preferences.appendingPathComponent("codex-observations.json")
        guard let bytes = try? Data(contentsOf: file), bytes.count <= 2_000_000,
              let saved = try? JSONDecoder().decode(CodexTelemetryStore.self, from: bytes) else { return }
        telemetry = saved
        for key in telemetry.runs.keys where telemetry.runs[key]?.terminal == false {
            telemetry.runs[key]?.offlineUnknown = true; telemetry.runs[key]?.state = "unverified"
        }
    }
    func saveTelemetry() {
        if telemetry.runs.count > 100 {
            for key in telemetry.runs.sorted(by: { $0.value.lastActivity < $1.value.lastActivity }).prefix(telemetry.runs.count - 100).map({ $0.key }) where telemetry.runs[key]?.terminal == true {
                telemetry.runs.removeValue(forKey: key)
            }
        }
        if telemetry.tokens.count > 100 {
            for key in telemetry.tokens.sorted(by: { $0.value.updated < $1.value.updated }).prefix(telemetry.tokens.count - 100).map({ $0.key }) { telemetry.tokens.removeValue(forKey: key) }
        }
        do {
            try NativeWorkbench.safeDirectory(preferences)
            try JSONEncoder().encode(telemetry).write(to: preferences.appendingPathComponent("codex-observations.json"), options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: preferences.appendingPathComponent("codex-observations.json").path)
            telemetrySaveError = false
        } catch { telemetrySaveError = true }
    }
    func startObservationTimer() {
        guard observationTimer == nil else { return }
        observationTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            self.tickObservations()
            let now = Date().timeIntervalSince1970
            if self.connected && now >= self.usageRetryAfter && (now - self.usageRequestedAt >= 300 || self.quotaResetNeedsRead(now: now)) { self.refreshUsage() }
            self.publishTelemetry()
        }
    }
    func quotaResetNeedsRead(now: Double) -> Bool {
        guard let bytes = telemetry.limits, let data = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any] else { return false }
        let buckets = data["rateLimitsByLimitId"] as? [String: [String: Any]]
        let rows = buckets?.values.map { $0 } ?? [(data["rateLimits"] as? [String: Any]) ?? [:]]
        return rows.contains { row in
            ["primary", "secondary"].contains { key in
                guard let reset = (row[key] as? [String: Any])?["resetsAt"] as? Double else { return false }
                return reset <= now && reset > (telemetry.limitsUpdated ?? 0)
            }
        }
    }
    func tickObservations(uptime: Double = ProcessInfo.processInfo.systemUptime) {
        let delta = max(0, uptime - observationTick); observationTick = uptime
        guard connected, !uncertain, let thread = threadID, let turn = turnID, var run = telemetry.runs[thread + "/" + turn], !run.terminal else { return }
        // A delayed callback may span sleep/disconnection. Do not label it active.
        run.observedElapsed += delta
        if delta > 5 { run.offlineUnknown = true }
        else if delta > 0 && run.serviceInterrupted != true {
            if run.requests.isEmpty { run.activeSeconds += delta } else { run.waitSeconds += delta }
        }
        telemetry.runs[thread + "/" + turn] = run
        if uptime - observationSavedAt >= 10 { observationSavedAt = uptime; saveTelemetry() }
    }
    static func telemetryError(_ message: String?) -> String {
        let value = (message ?? "read failed").lowercased()
        if value.contains("method not found") || value.contains("unsupported") || value.contains("not supported") { return "unsupported" }
        if value.contains("401") || value.contains("403") || value.contains("auth") || value.contains("login") { return "authentication" }
        if value.contains("capacity") { return "capacity" }
        if value.contains("quota") || value.contains("credits exhausted") || value.contains("usage limit") { return "quota" }
        if value.contains("429") || value.contains("rate limit") { return "rate_limit" }
        if value.contains("network") || value.contains("connect") || value.contains("timeout") { return "network" }
        return "unavailable"
    }
    func refreshUsage() {
        let now = Date().timeIntervalSince1970
        guard connected, !usageReading, now - usageRequestedAt >= 10 else { publishTelemetry(); return }
        usageRequestedAt = now; usageReading = true; usageGeneration += 1
        let generation = usageGeneration
        request("account/read", ["refreshToken": false]) { [weak self] result in
            guard let self = self, generation == self.usageGeneration else { return }
            guard let result = result, let account = result["account"] as? [String: Any] else {
                self.usageReading = false; self.usageErrors["account"] = Self.telemetryError(self.lastRequestFailure)
                if self.usageErrors["account"] == "authentication" { self.accountVerified = false }
                self.usageRetryAfter = Date().timeIntervalSince1970 + self.usageBackoff; self.usageBackoff = min(1800, self.usageBackoff * 2); self.publishTelemetry(); return
            }
            let auth = account["type"] as? String ?? "unknown"
            let routing = result["workspaceRouting"] as? [String: Any]
            // Identity is scoped by the formal connection, never by a copied credential.
            let scope = routing?["chatgptAccountId"] as? String
            let identity = Self.digest(Data((auth + ":" + (routing?["backendOrigin"] as? String ?? "") + ":" + (scope ?? self.telemetrySessionIdentity)).utf8))
            if identity != self.telemetry.accountIdentity {
                let runs = self.telemetry.runs
                self.telemetry = CodexTelemetryStore()
                self.telemetry.runs = runs // Run identity is thread-scoped, not account quota.
                self.telemetry.accountIdentity = identity
            }
            self.telemetry.authentication = auth; self.telemetry.plan = account["planType"] as? String
            self.accountVerified = true; self.usageErrors.removeValue(forKey: "account")
            var left = 2
            for (method, field) in [("account/rateLimits/read", "limits"), ("account/usage/read", "usage")] {
                self.request(method, [:]) { [weak self] data in
                    guard let self = self, generation == self.usageGeneration else { return }
                    if let data = data, let encoded = try? JSONSerialization.data(withJSONObject: data) {
                        let receivedAccount = data["accountId"] as? String
                        if let receivedAccount = receivedAccount, let scope = scope, receivedAccount != scope {
                            self.accountVerified = false; self.usageErrors[field] = "account_changed"
                        } else {
                            if field == "limits" { self.telemetry.limits = encoded; self.telemetry.limitsUpdated = Date().timeIntervalSince1970 }
                            else { self.telemetry.usage = encoded; self.telemetry.usageUpdated = Date().timeIntervalSince1970 }
                            self.usageErrors.removeValue(forKey: field)
                        }
                    } else { self.usageErrors[field] = Self.telemetryError(self.lastRequestFailure) }
                    left -= 1; if left == 0 {
                        self.usageReading = false
                        self.usageBackoff = self.usageErrors.isEmpty ? 300 : min(1800, self.usageBackoff * 2)
                        self.usageRetryAfter = self.usageErrors.isEmpty ? 0 : Date().timeIntervalSince1970 + self.usageBackoff
                        self.saveTelemetry()
                    }
                    self.publishTelemetry()
                }
            }
        }
    }
    func accountNotification(_ method: String, _ p: [String: Any]) -> Bool {
        if method == "account/updated" {
            accountVerified = false; usageGeneration += 1; usageReading = false; usageRequestedAt = 0
            // Hide previous account values immediately, before asynchronous re-read.
            publishTelemetry(); refreshUsage(); return true
        }
        if method == "account/rateLimits/updated" {
            // Refresh via account-scoped read, not an unscoped event that could
            // race an account switch. Rate-limited to one read per ten seconds.
            refreshUsage(); return true
        }
        return false
    }
    func observeEvent(_ method: String, _ p: [String: Any], requestID: Any? = nil, now: Double = Date().timeIntervalSince1970) {
        guard let thread = p["threadId"] as? String, thread == threadID else { return }
        let turn = p["turn"] as? [String: Any] ?? [:]
        let resolvedTurn = method == "serverRequest/resolved" ? telemetry.runs.values.first(where: { $0.thread == thread && $0.requests[String(describing: p["requestId"] ?? "")] != nil })?.turn : nil
        guard let tid = (p["turnId"] as? String) ?? (turn["id"] as? String) ?? resolvedTurn else { return }
        let key = thread + "/" + tid
        if method == "thread/tokenUsage/updated", let usage = p["tokenUsage"] as? [String: Any] {
            func fields(_ raw: Any?) -> [String: Int] {
                let keys = ["inputTokens", "cachedInputTokens", "cacheWriteInputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens"]
                return (raw as? [String: Any] ?? [:]).reduce(into: [:]) { out, pair in
                    if keys.contains(pair.key), let n = pair.value as? Int, n >= 0 { out[pair.key] = n }
                }
            }
            telemetry.tokens[thread] = CodexTokenSnapshot(turn: tid, total: fields(usage["total"]), last: fields(usage["last"]), updated: now)
            saveTelemetry(); publishTelemetry(); return
        }
        tickObservations()
        if telemetry.runs[key] == nil {
            guard ["turn/started", "turn/completed"].contains(method) else { return }
            telemetry.runs[key] = CodexRunObservation(thread: thread, turn: tid, started: turn["startedAt"] as? Double, lastActivity: now)
        }
        guard var run = telemetry.runs[key], !run.terminal else { return }
        run.lastActivity = now
        if method == "error" { run.serviceInterrupted = true; run.offlineUnknown = true }
        else if method.hasPrefix("item/") || method == "turn/plan/updated" { run.serviceInterrupted = false }
        if let model = turn["model"] as? String { run.returnedModel = model }
        if method == "turn/started" {
            // A start event confirms execution even when this runtime omits startedAt.
            if run.started == nil { run.started = (turn["startedAt"] as? Double) ?? now; run.observedElapsed = max(0, now - run.started!) }
            run.state = "running"
            run.requestedModel = ledger.submissions.first(where: { $0.id == activeSubmission })?.model
        }
        if method == "turn/completed" {
            run.state = turn["status"] as? String ?? "failed"
            run.ended = (turn["completedAt"] as? Double) ?? now
            run.serviceDuration = (turn["durationMs"] as? Double).map { max(0, $0 / 1000) }
            run.activeTools.removeAll(); run.requests.removeAll()
        }
        if let item = p["item"] as? [String: Any], let iid = item["id"] as? String,
           ["commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "webSearch", "imageGeneration", "collabAgentToolCall"].contains(item["type"] as? String ?? "") {
            run.tools.insert(iid)
            if method == "item/started" { run.activeTools.insert(iid) }
            if method == "item/completed" { run.activeTools.remove(iid) }
        }
        if let item = p["item"] as? [String: Any], item["type"] as? String == "enteredReviewMode" { run.state = "verification" }
        if let item = p["item"] as? [String: Any], item["type"] as? String == "exitedReviewMode" { run.state = "running" }
        if let rid = requestID { run.requests[String(describing: rid)] = method == "item/tool/requestUserInput" ? "waiting_input" : "waiting_approval" }
        if method == "serverRequest/resolved", let rid = p["requestId"] { run.requests.removeValue(forKey: String(describing: rid)) }
        if method == "turn/plan/updated" { run.planUpdate(p["plan"] as? [[String: Any]] ?? []) }
        telemetry.runs[key] = run
        if !method.hasSuffix("Delta") && !method.hasSuffix("/delta") { saveTelemetry(); publishTelemetry() }
    }
    func reconcileObservations(thread: String, turns: [[String: Any]]) {
        // History reconciles terminal metadata, never replays events or counts.
        for turn in turns {
            guard let tid = turn["id"] as? String, var run = telemetry.runs[thread + "/" + tid] else { continue }
            if let status = confirmedHistoryTerminal(turn) {
                run.state = status; run.ended = turn["completedAt"] as? Double ?? run.ended
                run.serviceDuration = (turn["durationMs"] as? Double).map { max(0, $0 / 1000) } ?? run.serviceDuration
                run.requests.removeAll(); run.activeTools.removeAll()
            }
            run.started = turn["startedAt"] as? Double ?? run.started
            telemetry.runs[thread + "/" + tid] = run
        }
        saveTelemetry(); publishTelemetry()
    }
    func refreshRunObservation() {
        guard connected, let id = threadID, !runReading else { return }
        runReading = true
        request("thread/turns/list", ["threadId": id, "limit": 10, "sortDirection": "desc", "itemsView": "full"]) { [weak self] response in
            guard let self = self else { return }; self.runReading = false
            if let turns = response?["data"] as? [[String: Any]] { self.reconcileObservations(thread: id, turns: turns) }
            else { self.usageErrors["run"] = Self.telemetryError(self.lastRequestFailure); self.publishTelemetry() }
        }
    }
    func observedSubmission(for run: CodexRunObservation) -> CodexSubmission? {
        ledger.submissions.first { $0.thread == run.thread && $0.turn == run.turn }
    }
    func publishTelemetry() {
        let now = Date().timeIntervalSince1970
        func object(_ data: Data?) -> Any { data.flatMap { try? JSONSerialization.jsonObject(with: $0) } ?? NSNull() }
        var payload: [String: Any] = ["connected": connected, "accountVerified": accountVerified, "reading": usageReading,
            "authentication": accountVerified ? telemetry.authentication ?? "unknown" : "unknown", "plan": accountVerified ? telemetry.plan ?? "unknown" : "unknown", "errors": usageErrors,
            "limits": accountVerified ? object(telemetry.limits) : NSNull(), "usage": accountVerified ? object(telemetry.usage) : NSNull(),
            "limitsUpdated": telemetry.limitsUpdated ?? 0, "usageUpdated": telemetry.usageUpdated ?? 0,
            "now": now, "saveError": telemetrySaveError, "threadId": threadID ?? ""]
        if accountVerified, let id = threadID, let token = telemetry.tokens[id], let data = try? JSONEncoder().encode(token) { payload["tokens"] = object(data) }
        if let id = threadID {
            let runs = telemetry.runs.values.filter { $0.thread == id }
            payload["observedTurns"] = runs.count; payload["observedTools"] = runs.reduce(0) { $0 + $1.tools.count }
            if let run = runs.sorted(by: { $0.lastActivity > $1.lastActivity }).first {
                // The default composer mode is Steer even when idle; that
                // input starts a new turn. The earliest exactly linked input,
                // not its composer label, identifies this turn's submission.
                let submission = observedSubmission(for: run)
                var state = run.state
                if !run.terminal {
                    if !connected || uncertain || run.serviceInterrupted == true { state = "unverified" }
                    else if let waiting = run.requests.values.sorted().first { state = waiting }
                    else if !run.activeTools.isEmpty { state = "tool" }
                }
                payload["run"] = ["state": state, "submitted": submission?.createdAt as Any? ?? NSNull(), "started": run.started as Any? ?? NSNull(),
                    "wallTimes": run.wallTimes(submitted: submission?.createdAt, now: now),
                    "ended": run.ended as Any? ?? NSNull(), "elapsed": run.serviceDuration as Any? ?? (run.started == nil ? NSNull() : run.observedElapsed),
                    "observedActive": run.activeSeconds, "observedWait": run.waitSeconds, "offlineUnknown": run.offlineUnknown,
                    "lastActivity": run.lastActivity, "tools": run.tools.count, "planDone": run.plan.values.filter { $0 == "completed" }.count,
                    "planTotal": run.plan.count, "planRevisions": run.planRevisions, "eta": run.estimate(now: now, online: connected && !uncertain),
                    "workload": run.workload(now: now, online: connected && !uncertain), "turnId": run.turn,
                    "requestedModel": run.requestedModel ?? submission?.model ?? "unknown", "returnedModel": run.returnedModel ?? "unknown",
                    "returnState": submission?.returnState ?? "not_recorded", "businessResult": submission?.businessResult ?? "unverified"]
            }
            if turnID == nil, let queued = ledger.submissions.first(where: { $0.thread == id && ["queued", "preparing", "sending", "accepted", "unknown"].contains($0.state) && $0.turn == nil }) {
                payload["queued"] = ["submitted": queued.createdAt, "state": queued.state]
            }
        }
        emit("telemetry", payload)
        statusMetadataChanged?()
    }
}
