import AppKit
import UniformTypeIdentifiers
import WebKit

// A dedicated local view owns the team's sessions. The two ordinary panes keep
// their views, drafts and permissions while the owner changes views.
final class TeamWorkspace: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
  let managed: Bool
  var roomChanged: (() -> Void)?
  var showRoom: (() -> Void)?
  let web: WKWebView
  private let root: URL, directory: URL, page: URL
  private let translate: (String) -> String
  private let codex: NativeCodex
  private let preferences: URL
  private var channels: [String: NativeWorkbench] = [:]
  private var models: [String: String] = [:], inspecting = Set<String>()
  private var selectedServices = ["Planner": "Codex", "Builder": "Codex", "Reviewer": "Claude"]
  private var viewed: TeamRun?, history: [String: [String: Any]] = [:]
  private var archiveIssues = 0, loadingHistory = false
  private var savedDraft: [String: String] = [:]
  private var draftSave: DispatchWorkItem?
  private let earlierDirectories: [URL]
  private func memberService(_ role: String) -> String {
    run?.members.first(where: { $0.role == role })?.service ?? selectedServices[role] ?? "Codex"
  }
  private func channelKey(_ role: String, _ service: String) -> String { role + "-" + service }
  private func channel(_ role: String, _ service: String) -> NativeWorkbench {
    let key = channelKey(role, service)
    if let w = channels[key] { return w }
    let w = NativeWorkbench(
      preferences: preferences, translate: translate, openProjects: {},
      serviceHome: URL(string: TeamMember.homes[service]!)!,
      locationKey: key == "Reviewer-Claude" ? "team-review-location.json" : "team-" + key + ".json",
      handoffResources: root)
    channels[key] = w
    return w
  }
  private func prepareChannel(_ role: String, _ service: String, fresh: Bool = false) {
    guard let home = TeamMember.homes[service] else { return }
    let w = channel(role, service)
    if fresh || w.web.url == nil { w.start(embedded: true, navigateTo: URL(string: home)) }
    inspectModel(role, service)
  }
  private var codexWindow: NSWindow?
  private var timer: Timer?, lock: Int32 = -1
  private(set) var run: TeamRun?
  private var proposed: TeamRun?, selectedFolder: CodexDirectory?
  private var notice = "", checking = false, picker = false
  private var creating: String?, pollCount = 0, storageOK = true, loaded = false
  private var usageAttempt: String?, usageFirstCheck: Date?, usageGeneration: Int?
  private var evidenceCheck: UUID?
  private var awaitingSelection: (member: String, since: Date)?
  private var checkedMember: TeamMember?
  private var recoveryProbe: UUID?, recoveryState = "", recoveryStep = "", recoveryChecked: Double = 0
  private var observingWeb: String?
  private var lastPayload: Data?
  private var observationDeadline: Date?, terminationObserver: NSObjectProtocol?

  init(root: URL, preferences: URL, translate: @escaping (String) -> String, managed: Bool = false, initialRecord:TeamRun?=nil) {
    self.managed = managed
    self.preferences = preferences
    self.root = root
    self.translate = translate
    directory = managed ? preferences : preferences.appendingPathComponent("team-r1")
    let productProfile = preferences.lastPathComponent == "Tianma Work OS Preferences"
    let support = productProfile ? preferences.deletingLastPathComponent()
      : FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")
    // Newest snapshot first when the same chat was imported through both previews.
    let names = productProfile ? ["TWOS AI Team Acceptance", "TWOS AI Team R1 Preview"]
      : ["TWOS AI Team R1 Preview"]
    let current = preferences.standardizedFileURL.path
    earlierDirectories = names.map { support.appendingPathComponent($0) }
      .filter { $0.standardizedFileURL.path != current }
      .map { $0.appendingPathComponent("team-r1") }
      .filter { FileManager.default.fileExists(atPath: $0.path) }
    page = root.appendingPathComponent("ai_team/legacy.html")
    let config = WKWebViewConfiguration()
    config.websiteDataStore = .nonPersistent()
    web = WKWebView(frame: .zero, configuration: config)
    codex = NativeCodex(
      resources: root, preferences: directory.appendingPathComponent("codex"), translate: translate)
    super.init()
    codex.teamSession = true
    web.navigationDelegate = self
    config.userContentController.add(self, name: "team")
    do {
      try NativeWorkbench.safeDirectory(directory)
      lock = open(
        directory.appendingPathComponent("lock").path, O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC,
        0o600)
      guard lock >= 0, flock(lock, LOCK_EX | LOCK_NB) == 0 else { throw TeamError.busy }
      let draftURL = directory.appendingPathComponent("setup-draft.json")
      if let data = try? Data(contentsOf: draftURL),
        let d = try? JSONDecoder().decode([String: String].self, from: data)
      {
        savedDraft = d
        for role in TeamMember.roles {
          if let service = d[role + "Service"], TeamMember.services.contains(service) {
            selectedServices[role] = service
          }
        }
      }
      if !managed {loadHistory(from: [directory], importing: false)}
      let head = directory.appendingPathComponent("current")
      if FileManager.default.fileExists(atPath: head.path) {
        let id = try String(contentsOf: head, encoding: .utf8)
        guard UUID(uuidString: id) != nil else { throw TeamError.storage }
        if managed,let initialRecord,initialRecord.id==id {run=initialRecord} else {run = try readRun(id)}
        guard let current = run, current.id == id else { throw TeamError.storage }
        remember(current)
        if current.pendingDecision != nil {
          do { try applyDecision() } catch { notice = "decisionConflict" }
        }
        if run?.state == "running" || run?.state == "stopping" {
          run?.state = "paused"
          run?.reason = "restart"
          try persist()
        }
      }
    } catch {
      storageOK = false
      notice = (error as? TeamError)?.rawValue ?? "storage"
    }
    terminationObserver = NotificationCenter.default.addObserver(
      forName: NSApplication.willTerminateNotification, object: nil, queue: .main
    ) { [weak self] _ in self?.shutdown() }
    if !managed { web.loadFileURL(page, allowingReadAccessTo: page.deletingLastPathComponent()) }
  }
  func shutdown() {
    draftSave?.cancel()
    if !managed && storageOK && lock >= 0 { writeSetupDraft() }
    recoveryProbe = nil
    evidenceCheck = nil
    timer?.invalidate()
    timer = nil
    if let token = terminationObserver {
      NotificationCenter.default.removeObserver(token)
      terminationObserver = nil
    }
    if run?.state == "running" || run?.state == "stopping" {
      run?.state = "paused"
      run?.reason = "restart"
      try? persist()
    }
    web.configuration.userContentController.removeScriptMessageHandler(forName: "team")
    for w in channels.values {
      w.web.stopLoading()
      w.close()
    }
    codex.disconnect()
    if lock >= 0 {
      close(lock)
      lock = -1
    }
    storageOK = false
  }
  var hasActiveCodexTurn: Bool { codex.isBusy || codex.submissionPending }
  private var unreadReview: TeamAttempt? {
    guard let r = run, r.state == "blocked", ["invalidReply", "invalidReview"].contains(r.reason),
      let a = r.attempts.last, a.role == "Reviewer", a.state == "completed",
      a.web?.resolvedURL == a.thread, a.thread != nil, a.resultHash != nil, a.turn != nil,
      let v = r.versions.last, a.version == v.number, v.review == nil
    else { return nil }
    return a
  }
  private func connectTeamChannels() {
    if let r = run {
      for m in r.members where m.service != "Codex" {
        if let w = r.attempts.last(where: { $0.role == m.role && $0.web != nil })?.web {
          restoreReviewer(w, role: m.role)
        } else {
          prepareChannel(m.role, m.service)
        }
      }
    } else {
      for role in TeamMember.roles { prepareChannel(role, memberService(role)) }
    }
    codex.connect()
  }
  private func restoreReviewer(_ receipt: WebHandoffReceipt, role: String) {
    guard TeamMember.homes[receipt.provider] != nil else { return }
    let reviewer = channel(role, receipt.provider)
    if let raw = receipt.resolvedURL, let url = URL(string: raw),
      NativeWorkbench.restorableURL(reviewer.web.url, service: reviewer.serviceHome) != url
    {
      reviewer.start(embedded: true, navigateTo: url)
    } else {
      reviewer.start(embedded: true)
    }
  }
  private func readRun(_ id: String) throws -> TeamRun { try Self.readRecord(id, from: directory) }
  static func readRecord(_ id: String, from directory: URL) throws -> TeamRun {
    guard UUID(uuidString: id) != nil else { throw TeamError.storage }
    let path = directory.appendingPathComponent(id + ".json").path
    let fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW)
    guard fd >= 0 else { throw TeamError.storage }
    let h = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
    defer { try? h.close() }
    var st = stat()
    guard fstat(fd, &st) == 0, st.st_mode & S_IFMT == S_IFREG, st.st_uid == getuid(),
      st.st_size <= 134_217_728, let bytes = try h.readToEnd()
    else { throw TeamError.storage }
    let r = try JSONDecoder().decode(TeamRun.self, from: bytes)
    guard r.id == id else { throw TeamError.storage }
    return r
  }
  private func loadHistory(from sources: [URL], importing: Bool) {
    guard !loadingHistory else { return }
    loadingHistory = true
    let destination = directory
    DispatchQueue.global(qos: .utility).async { [weak self] in
      var found: [String: [String: Any]] = [:]
      var errors = 0
      for source in sources {
        do {
          let attrs = try nativePathMetadata(source.path)
          guard attrs.st_uid == getuid(), attrs.st_mode & S_IFMT == S_IFDIR,
            source.resolvingSymlinksInPath().standardizedFileURL.path
              == source.standardizedFileURL.path
          else { throw TeamError.storage }
          let urls = try FileManager.default.contentsOfDirectory(
            at: source, includingPropertiesForKeys: nil)
          for url in urls where url.pathExtension == "json" {
            let id = url.deletingPathExtension().lastPathComponent
            guard UUID(uuidString: id) != nil else { continue }
            do {
              let r = try Self.readRecord(id, from: source)
              if importing {
                let file = destination.appendingPathComponent(id + ".json")
                if FileManager.default.fileExists(atPath: file.path) { continue }
                // The profile owns the single-writer lock. Publish only complete,
                // read-only archive snapshots; never import current, leases or cookies.
                let temp = destination.appendingPathComponent(".import-" + UUID().uuidString)
                defer { try? FileManager.default.removeItem(at: temp) }
                try TeamFiles.bytes(r).write(to: temp, options: .withoutOverwriting)
                guard link(temp.path, file.path) == 0 else {
                  if errno == EEXIST { continue }
                  throw TeamError.storage
                }
              }
              found[id] = ["id": id, "title": r.goal, "created": r.created, "state": r.state]
            } catch { errors += 1 }
          }
        } catch { errors += 1 }
      }
      DispatchQueue.main.async { [weak self, found, errors] in
        guard let self = self else { return }
        self.loadingHistory = false
        guard self.storageOK, self.lock >= 0 else { return }
        self.history.merge(found) { current, _ in current }
        self.archiveIssues += errors
        if importing { self.notice = errors > 0 ? "archiveError" : "archiveLoaded" }
        self.publish()
      }
    }
  }
  private func saveSetupDraft() {
    draftSave?.cancel()
    let work = DispatchWorkItem { [weak self] in self?.writeSetupDraft() }
    draftSave = work
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.25, execute: work)
  }
  private func writeSetupDraft() {
    guard storageOK, lock >= 0 else { return }
    do {
      try TeamFiles.bytes(savedDraft).write(
        to: directory.appendingPathComponent("setup-draft.json"), options: .atomic)
    } catch {
      notice = "storage"
      publish()
    }
  }
  private func applyDecision() throws {
    guard var r = run, let intent = r.pendingDecision, r.state == "awaitingOwner",
      ["accept", "changes"].contains(intent.action), let path = r.exported,
      intent.digest == r.versions.last?.digest,
      URL(fileURLWithPath: path).deletingLastPathComponent().standardizedFileURL.path
        == r.folder.path
    else { throw TeamError.wrongVersion }
    let leaf = URL(fileURLWithPath: path).lastPathComponent
    let previous = try r.delivery()
    r.owner = intent.action == "accept" ? "accepted" : "changes"
    r.state = r.owner
    r.comment = intent.comment
    let updated = try r.delivery()
    try checkDelivery(previous.filter { $0.key != "delivery.json" }, folder: r.folder, name: leaf)
    try TeamFiles.updateDecision(
      in: r.folder, leaf: leaf, previous: previous["delivery.json"]!,
      next: updated["delivery.json"]!)
    r.pendingDecision = nil
    run = r
    try persist()
    notice = ""
  }
  private func remember(_ r: TeamRun) {
    history[r.id] = ["id": r.id, "title": r.goal, "created": r.created, "state": r.state]
  }
  func present() {
    guard storageOK else {
      publish()
      return
    }
    if timer == nil {
      connectTeamChannels()
      let t = Timer(timeInterval: 1, repeats: true) { [weak self] _ in self?.tick() }
      timer = t
      RunLoop.main.add(t, forMode: .common)
    }
    publish()
  }
  func webView(
    _ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
    decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
  ) {
    decisionHandler(
      action.targetFrame?.isMainFrame == true
        && action.request.url?.standardizedFileURL == page.standardizedFileURL ? .allow : .cancel)
  }
  func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
    loaded = true
    lastPayload = nil
    publish()
  }
  private var canLeaveCurrentTask: Bool {
    guard let run else { return true }
    return evidenceCheck == nil && run.pending == nil && run.pendingDecision == nil
      && ["accepted", "changes", "blocked", "stopped"].contains(run.state)
  }
  func publish() {
    if managed {roomChanged?();return}
    guard loaded else { return }
    var data: [String: Any] = [
      "zh": translate("Back") != "Back", "sample": TeamFiles.sample,
      "catalog": codex.modelCatalog.compactMap { $0["model"] as? String },
      "reviewer": models["Reviewer-Claude"] ?? "",
      "services": selectedServices, "webModels": models, "draft": savedDraft,
      "canImport": !earlierDirectories.isEmpty,
      "loadingHistory": loadingHistory,
      "history": history.values.sorted {
        ($0["created"] as? Double ?? 0) > ($1["created"] as? Double ?? 0)
      },
      "archiveIssues": archiveIssues, "current": run?.id ?? "", "archived": viewed != nil,
      "codex": codex.connectionPhase, "folder": selectedFolder?.path ?? "", "notice": notice,
      "writable": storageOK, "canNew": storageOK && canLeaveCurrentTask,
    ]
    if let p = proposed {
      data["proposal"] = [
        "id": p.id, "goal": p.goal, "directory": p.folder.path,
        "members": p.members.map { [$0.role, $0.product, $0.model, $0.displayName ?? ""] },
      ]
    }
    if let r = viewed ?? run {
      data["run"] =
        [
          "id": r.id, "state": r.state, "next": r.next, "reason": r.reason, "goal": r.goal,
          "folder": r.folder.path, "workPath": r.workPath, "created": r.created,
          "ownerComment": r.comment, "pendingDecision": r.pendingDecision != nil,
          "chat": chatRows(r), "messages": (try? TeamFiles.json(r.messages ?? [])) ?? "[]",
          "timeline": (try? TeamFiles.json(r.milestones ?? [])) ?? "[]",
          "memberSelections": r.memberSelections ?? [:],
          "owner": r.owner, "version": r.versions.count, "unreadReview": unreadReview != nil,
          "recoverMemberReply": r.canRecoverMemberReply,
          "members": r.members.map { [$0.role, $0.product, $0.model, $0.displayName ?? ""] },
          "out": r.exported ?? "",
        ] as [String: Any]
    }
    guard let encoded = try? JSONSerialization.data(withJSONObject: data, options: .sortedKeys),
      encoded != lastPayload
    else { return }
    lastPayload = encoded
    web.callAsyncJavaScript(
      "window.renderTeam(state)", arguments: ["state": data], in: nil, in: .page,
      completionHandler: nil)
  }
  private func chatRows(_ r: TeamRun) -> [[String: Any]] {
    r.attempts.map { a -> [String: Any] in
      let member = r.members.first { $0.role == a.role }
      var result: [String: Any] = [
        "id": a.id, "role": a.role, "service": member?.service ?? "",
        "requested": member?.model ?? "", "observedSelection": a.observedWebSelection ?? "",
        "model": a.model ?? "", "state": a.state, "version": a.version, "started": a.started,
        "finished": a.finished ?? 0, "reply": a.replyText ?? a.web?.result ?? "",
        "activity": (try? TeamFiles.json(a.activity ?? [])) ?? "[]", "inputHash": a.inputHash,
        "resultHash": a.resultHash ?? "",
        "thread": a.thread ?? "", "turn": a.turn ?? "", "prompt": a.promptText ?? a.web?.text ?? "",
      ]
      if a.role == "Planner", let p = r.plan { result["plan"] = try? TeamFiles.json(p) }
      if a.role != "Planner", let v = r.versions.first(where: { $0.number == a.version }) {
        result["digest"] = v.digest
        if a.role == "Builder" {
          result["report"] = try? TeamFiles.json(v.report)
        } else if let x = v.review {
          result["review"] = try? TeamFiles.json(x)
          result["verified"] = v.verified
        } else if let raw = v.unstructuredReview {
          result["feedback"] = raw
        }
      }
      if let rec = a.web {
        result["dispatch"] = rec.state
      } else if viewed == nil, let client = a.clientID, let thread = a.thread,
        let rec = codex.ledger.submissions.first(where: { $0.id == client && $0.thread == thread })
      {
        result["dispatch"] = rec.state
      }
      return result
    }
  }
  private func persist() throws {
    guard storageOK else { throw TeamError.storage }
    run?.recordState()
    guard let r = run else { throw TeamError.storage }
    do {
      let bytes=try TeamFiles.bytes(r)
      guard bytes.count<=134_217_728 else {throw TeamError.storage}
      try bytes.write(
        to: directory.appendingPathComponent(r.id + ".json"), options: .atomic)
      try Data(r.id.utf8).write(to: directory.appendingPathComponent("current"), options: .atomic)
      remember(r)
    } catch {
      storageOK = false
      notice = "storage"
      throw error
    }
  }
  private func fail(_ reason: String) {
    if run?.state == "running" {
      run?.state = "paused"
      run?.reason = reason
      try? persist()
    }
    notice = reason
    publish()
  }
  func userContentController(
    _ controller: WKUserContentController, didReceive message: WKScriptMessage
  ) {
    guard message.webView === web, message.frameInfo.isMainFrame,
      message.frameInfo.request.url?.standardizedFileURL == page.standardizedFileURL,
      let args = message.body as? [String: String], let action = args["action"], storageOK
    else { return }
    do {
      switch action {
      case "import":
        guard !earlierDirectories.isEmpty else { return }
        loadHistory(from: earlierDirectories, importing: true)
        publish()
        return
      case "draft":
        guard viewed == nil, run == nil, proposed == nil else { return }
        if let goal = args["goal"], goal.utf8.count <= 2400 { savedDraft["goal"] = goal }
        if let csv = args["csv"], csv.utf8.count <= 24000 { savedDraft["csv"] = csv }
        for role in TeamMember.roles {
          if let model = args[role], model.utf8.count < 160 { savedDraft[role] = model }
          if let name = args[role + "Name"], name.count <= 32 { savedDraft[role + "Name"] = name }
        }
        saveSetupDraft()
        return
      case "history":
        guard let id = args["id"], history[id] != nil else { throw TeamError.storage }
        viewed = id == run?.id ? nil : try readRun(id)
        publish()
        return
      case "current":
        viewed = nil
        publish()
        return
      default: break
      }
      guard viewed == nil || ["frozen", "reveal", "new"].contains(action) else { return }
      switch action {
      case "message":
        guard var r = run, r.id == args["id"], let key = args["key"], let body = args["text"] else {
          return
        }
        try r.addMessage(id: key, text: body, share: args["share"] == "yes")
        run = r
        try persist()
        notice = ""
      case "service":
        guard run == nil, let role = args["role"], TeamMember.roles.contains(role),
          let service = args["service"], TeamMember.services.contains(service)
        else { return }
        proposed = nil
        selectedServices[role] = service
        savedDraft[role + "Service"] = service
        saveSetupDraft()
        prepareChannel(role, service)
        notice = ""
      case "directory": pickFolder()
      case "csv": pickCSV()
      case "codex":
        guard let a = run?.pending, let thread = a.thread, thread == codex.threadID,
          codex.activeSubmission == (a.clientID ?? a.turn), !codex.approvals.isEmpty
        else {
          notice = "noApproval"
          break
        }
        if codexWindow == nil {
          let w = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 800, height: 640),
            styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
          w.isReleasedWhenClosed = false
          w.contentView = codex.web
          codexWindow = w
        }
        codexWindow?.title = "TWOS · AI Team · Codex"
        codexWindow?.makeKeyAndOrderFront(nil)
      case "reviewer":
        let role = args["role"] ?? run?.pending?.role ?? "Reviewer"
        guard TeamMember.roles.contains(role) else { return }
        let service = memberService(role)
        guard TeamMember.homes[service] != nil else { return }
        let w = channel(role, service)
        if w.web.url == nil { prepareChannel(role, service) }
        w.window?.title = "TWOS · " + service + " · " + role
        w.showWindow(nil)
        w.window?.makeKeyAndOrderFront(nil)
      case "refresh":
        if !codex.connected && !codex.connecting { codex.connectSelectedPane() }
        for role in TeamMember.roles { inspectModel(role, memberService(role)) }
      case "propose":
        guard run == nil, let f = selectedFolder, let goal = args["goal"], let csv = args["csv"]
        else { throw TeamError.unavailable }
        let members = try TeamMember.roles.map { role -> TeamMember in
          let service = memberService(role)
          guard let provider = TeamMember.providers[service], let model = args[role.lowercased()],
            args[role + "Service"] == service, !model.isEmpty,
            service == "Codex"
              ? codex.modelIDs.contains(model)
              : TeamMember.selectionLabels(model, service: service).contains((models[channelKey(role, service)] ?? "").lowercased())
          else { throw TeamError.unavailable }
          let name = args[role + "Name"]?.trimmingCharacters(in: .whitespacesAndNewlines)
          return TeamMember(
            role: role, product: service, provider: provider, model: model, displayName: name)
        }
        proposed = try TeamRun.create(goal: goal, csv: csv, folder: f, members: members)
        notice = ""
      case "edit": proposed = nil
      case "approve":
        guard run == nil, let p = proposed, p.id == args["id"], args["quota"] == "confirmed",
          try NativeCodex.inspectDirectory(p.folder.path, isolated: true)
            == p.folder,
          p.members.allSatisfy({ m in
            m.service == memberService(m.role)
              && (m.service == "Codex"
                ? codex.connected && codex.modelIDs.contains(m.model)
                : m.acceptsSelection(models[channelKey(m.role, m.service)]))
          })
        else { throw TeamError.unavailable }
        run = p
        try persist()
        savedDraft.removeAll()
        writeSetupDraft()
        proposed = nil
        notice = ""
        advance()
      case "stop": if run?.id == args["id"] { stop() }
      case "evidence":
        guard let r = run, r.id == args["id"], r.state == "blocked", r.reason == "identity",
          evidenceCheck == nil
        else { break }
        let check = UUID()
        evidenceCheck = check
        notice = "reconciling"
        // A disconnected transport or a page with an incomplete load cannot leave
        // the button permanently busy. Late callbacks belong to the prior check.
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
          guard let self = self, self.evidenceCheck == check else { return }
          self.evidenceCheck = nil
          self.notice = "identity"
          self.publish()
        }
        recheckEvidence(r.id, index: 0, check: check)
      case "recoverMemberReply":
        guard var r = run, r.id == args["id"] else { throw TeamError.wrongVersion }
        try r.recoverMemberReply()
        run = r
        try persist()
        notice = ""
      case "recheckReview":
        guard let a = unreadReview, let w = a.web, run?.id == args["id"], !checking else {
          throw TeamError.unavailable
        }
        let reviewer = channel(a.role, w.provider)
        if reviewer.web.url?.absoluteString != a.thread {
          restoreReviewer(w, role: a.role)
          notice = "reviewerLoading"
          break
        }
        var request = w.request(inspectOnly: true)
        request["teamReview"] = true
        checking = true
        reviewer.webTransfer(request) { [weak self] response in
          guard let self = self else { return }
          self.checking = false
          guard var r = self.run, self.unreadReview?.id == a.id,
            response["state"] as? String == "reply",
            response["conversationURL"] as? String == a.thread,
            response["replyMessage"] as? String == a.turn, let text = response["reply"] as? String,
            NativeCodex.digest(Data(text.utf8)) == a.resultHash,
            let thread = a.thread, let turn = a.turn
          else {
            self.notice = "unconfirmed"
            self.publish()
            return
          }
          // Re-interpret only the exact previously received bytes. New dispatch
          // requires a separate explicit continuation within the original limits.
          r.attempts[r.attempts.count - 1].state = "sent"
          r.state = "paused"
          r.reason = ""
          self.run = r
          self.finish(a, text: text, actual: a.model, source: a.source, thread: thread, turn: turn)
        }
      case "resume":
        guard let r = run, r.id == args["id"], r.state == "paused" else {
          throw TeamError.unavailable
        }
        if r.expired && r.pending == nil {
          stop(reason: "timeout")
          return
        }
        if let a = r.pending {
          // Restart/check uses only the recorded operation, never a new send.
          if let w = a.web {
            restoreReviewer(w, role: a.role)
            observingWeb = a.id
            observationDeadline = Date().addingTimeInterval(15)
            notice = "reconciling"
            publish()
            return
          } else if let t = a.thread, codex.threadID != t {
            codex.selectThread(t)
          }
          if let t = a.thread, t == codex.threadID, codex.uncertain { codex.reconcileDelivery() }
          observationDeadline = Date().addingTimeInterval(15)
          notice = "reconciling"
        }
        run?.state = (r.stopRequested == true || r.expired) ? "stopping" : "running"
        run?.reason = ""
        try persist()
        advance()
      case "export", "accept", "changes":
        guard var r = run, r.id == args["id"], r.state == "awaitingOwner",
          action != "changes"
            || !(args["comment"] ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { throw TeamError.invalidReview }
        if action != "export" {
          guard r.exported != nil, let version = r.versions.last else {
            throw TeamError.invalidReview
          }
          if let pending = r.pendingDecision {
            guard pending.action == action else { throw TeamError.wrongVersion }
          } else {
            // Check the full previous receipt before recording the Owner's decision.
            try checkDelivery(
              try r.delivery(), folder: r.folder,
              name: URL(fileURLWithPath: r.exported!).lastPathComponent)
            r.pendingDecision = TeamRun.OwnerDecision(
              action: action, comment: String((args["comment"] ?? "").prefix(1000)),
              digest: version.digest)
            run = r
            try persist()
          }
          try applyDecision()
        } else {
          try export(&r)
          run = r
          try persist()
        }
      case "retryDecision":
        guard run?.id == args["id"] else { return }
        try applyDecision()
      case "frozen":
        guard let r = viewed ?? run, r.id == args["id"],
          let v = r.versions.first(where: {
            $0.number == (args["version"].flatMap(Int.init) ?? r.versions.count)
          })
        else {
          throw TeamError.wrongVersion
        }
        let filename = args["file"] ?? "dashboard.html"
        guard v.files[filename] != nil else { throw TeamError.wrongVersion }
        let path: URL
        if viewed != nil {
          let parent = try NativeCodex.inspectDirectory(r.workPath, isolated: true)
          try checkDelivery(v.files, folder: parent, name: r.frozenName(v.number))
          path = URL(fileURLWithPath: parent.path).appendingPathComponent(r.frozenName(v.number))
        } else {
          path = try freeze(v, run: r)
        }
        NSWorkspace.shared.activateFileViewerSelecting([path.appendingPathComponent(filename)])
      case "reveal":
        if let r = viewed ?? run, r.id == args["id"], let path = r.exported {
          try checkDelivery(
            try r.delivery(), folder: r.folder, name: URL(fileURLWithPath: path).lastPathComponent)
          let url = URL(fileURLWithPath: path)
          guard url.deletingLastPathComponent().standardizedFileURL.path == r.folder.path else {
            throw TeamError.changedDirectory
          }
          if let file = args["file"] {
            guard ["dashboard.html", "summary.md", "review.md", "delivery.json"].contains(file)
            else { throw TeamError.wrongVersion }
            NSWorkspace.shared.activateFileViewerSelecting([url.appendingPathComponent(file)])
          } else {
            NSWorkspace.shared.activateFileViewerSelecting([url])
          }
        }
      case "new":
        guard canLeaveCurrentTask, let r = run, r.id == args["id"] else { throw TeamError.busy }
        try FileManager.default.removeItem(at: directory.appendingPathComponent("current"))
        viewed = nil
        run = nil
        proposed = nil
        selectedFolder = nil
        notice = ""
        for w in channels.values {
          w.close()
          w.web.stopLoading()
        }
        channels.removeAll()
        models.removeAll()
        selectedServices = ["Planner": "Codex", "Builder": "Codex", "Reviewer": "Claude"]
        prepareChannel("Reviewer", "Claude", fresh: true)
      default: return
      }
    } catch { notice = (error as? TeamError)?.rawValue ?? "invalidInput" }
    publish()
  }
  private func pickFolder() {
    guard !picker, run == nil, let win = web.window else { return }
    let panel = NSOpenPanel()
    panel.canChooseDirectories = true
    panel.canChooseFiles = false
    panel.canCreateDirectories = true
    panel.message =
      translate("Back") == "Back"
      ? "Select an existing folder. This task will create its own delivery subfolder." : "选择已有目录。本任务会在其中创建专属交付子目录。"
    picker = true
    panel.beginSheetModal(for: win) { [weak self] response in
      guard let self = self else { return }
      self.picker = false
      guard response == .OK, let url = panel.url else { return }
      do {
        self.selectedFolder = try NativeCodex.inspectDirectory(
          url.path, isolated: true)
        self.proposed = nil
        self.notice = ""
      } catch {
        self.selectedFolder = nil
        self.proposed = nil
        self.notice = "deliveryFolderUnavailable"
      }
      self.publish()
    }
  }
  private func pickCSV() {
    guard !picker, run == nil, let win = web.window else { return }
    let p = NSOpenPanel()
    p.canChooseFiles = true
    p.canChooseDirectories = false
    p.allowsMultipleSelection = false
    p.allowedContentTypes = [.commaSeparatedText]
    picker = true
    p.beginSheetModal(for: win) { [weak self] response in
      guard let self = self else { return }
      self.picker = false
      guard response == .OK, let u = p.url else { return }
      do {
        let bytes = try WebTransferFile.read(u)
        guard let csv = String(data: bytes, encoding: .utf8) else { throw TeamError.invalidInput }
        _ = try TeamFiles.totals(csv)
        self.proposed = nil
        self.notice = ""
        self.web.callAsyncJavaScript(
          "window.teamCSV(csv)", arguments: ["csv": csv], in: nil, in: .page, completionHandler: nil
        )
      } catch { self.notice = "invalidInput" }
      self.publish()
    }
  }
  private func inspectModel(_ role: String, _ service: String, _ done: ((String) -> Void)? = nil) {
    let key = channelKey(role, service)
    guard let pane = channels[key], pane.web.url?.host == pane.serviceHome.host,
      !inspecting.contains(key)
    else {
      done?("")
      return
    }
    inspecting.insert(key)
    pane.web.callAsyncJavaScript(
      "return window.twosProviderDOM?.teamModel?.(allowMode) || ''",
      arguments: ["allowMode":managed], in: nil, in: NativeWorkbench.handoffWorld
    ) { [weak self, weak pane] result in
      guard let self = self else { return }
      self.inspecting.remove(key)
      guard let pane = pane, self.channels[key] === pane else {
        done?("")
        return
      }
      var value = ""
      if case .success(let s) = result, pane.web.url?.host == pane.serviceHome.host {
        value = s as? String ?? ""
      }
      self.models[key] = value
      if var r = self.run, ["running", "paused"].contains(r.state),
        let member = r.members.first(where: { $0.role == role && $0.service == service }),
        member.acceptsSelection(value), (r.memberSelections?[role] ?? member.model) != value {
        var selections = r.memberSelections ?? [:]
        selections[role] = value
        r.memberSelections = selections
        self.run = r
        try? self.persist()
      }
      done?(value)
      self.publish()
    }
  }
  private func tick() {
    pollCount += 1
    if managed {
      refreshSupplements()
      if run?.pending==nil, !["running","stopping"].contains(run?.state ?? ""), !codex.connecting,
         inspecting.isEmpty,observingWeb==nil {
        timer?.invalidate();timer=nil;publish();return
      }
    }
    if !managed, pollCount.isMultiple(of: 3), run == nil || run.map({ ["running", "paused"].contains($0.state) }) == true {
      for role in TeamMember.roles { inspectModel(role, memberService(role)) }
    }
    if let id = observingWeb, run?.state == "paused", let a = run?.pending, a.id == id {
      if let limit = observationDeadline, Date() < limit {
        pollReviewer(a)
      } else {
        observingWeb = nil
        observationDeadline = nil
        notice = "unconfirmed"
      }
    }
    if let r = run, ["running", "stopping"].contains(r.state) {
      if r.expired || r.pending.map({ Date().timeIntervalSince1970 - max($0.started, $0.web?.updatedAt ?? 0) >= 600 }) == true {
        if r.state == "running" { stop(reason: "timeout") }
      }
      if r.state == "stopping", let limit = observationDeadline, Date() >= limit {
        run?.state = "paused"
        run?.reason = "stopUnconfirmed"
        observationDeadline = nil
        try? persist()
      } else {
        advance()
      }
    }
    publish()
  }
  private func advance() {
    guard storageOK, var r = run, ["running", "stopping"].contains(r.state) else { return }
    if let a = r.pending {
      if a.web != nil { pollReviewer(a) } else { pollCodex(a) }
      return
    }
    guard r.state == "running" else { return }
    if r.expired {
      stop(reason: "timeout")
      return
    }
    do {
      let role = r.next
      guard let member = r.members.first(where: { $0.role == role }) else {
        throw TeamError.unavailable
      }
      if managed {
        guard prepareRoomStep(&r,member:member),let latest=run else{return}
        r=latest
      }
      if !managed, role == "Reviewer" {
        guard let version = r.versions.last else { throw TeamError.wrongVersion }
        _ = try freeze(version, run: r)
      }
      if member.service != "Codex" {
        guard !inspecting.contains(channelKey(role, member.service)) else { return }
        let expectedStep = r.conversation?.queue.first?.id
        inspectModel(role, member.service) { [weak self] m in
          guard let self = self, self.run?.id == r.id, self.run?.state == "running",
            self.run?.next == role, self.run?.pending == nil,
            self.run?.conversation?.queue.first?.id == expectedStep,
            self.run?.members.first(where: { $0.role == role }) == member
          else { return }
          if m.isEmpty {
            let key = r.id + "/" + role + "/" + member.service
            if self.awaitingSelection?.member != key { self.awaitingSelection = (key, Date()) }
            if let wait = self.awaitingSelection, Date().timeIntervalSince(wait.since) < 12 {
              self.notice = "readingMemberSelection"
              return
            }
          }
          self.awaitingSelection = nil
          if self.notice == "readingMemberSelection" { self.notice = "" }
          guard member.acceptsSelection(m) else {
            self.fail("reviewerChanged")
            return
          }
          self.dispatchWeb(member: member, selection: m)
        }
        return
      }
      if codex.connecting { return }
      guard codex.connected, codex.modelIDs.contains(member.model) else {
        fail("codexUnavailable")
        return
      }
      let prompt = try r.prompt()
      let a = try r.begin(prompt)
      run = r
      try persist()
      startCodex(a, model: member.model, prompt: prompt)
    } catch { fail((error as? TeamError)?.rawValue ?? "storage") }
  }
  private func startCodex(_ a: TeamAttempt, model: String, prompt: String) {
    guard let r = run else { return }
    do {
      let scope = try TeamFiles.taskDirectory(
        parent: managed ? try executionScratch() : try TeamFiles.workFolder(for:r), role:a.role, operation:a.id)
      guard
        try NativeCodex.inspectDirectory(scope.path, isolated: true, requireEmpty: true) == scope
      else { throw TeamError.changedDirectory }
      codex.previewDirectory(scope, create: false)
      guard let token = codex.pendingDirectory?.token else { throw TeamError.unavailable }
      creating = a.id
      codex.confirmDirectory(
        token: token, model: model, effort: a.memberSnapshot?.effort ?? "", reviewOnly: managed || a.role == "Reviewer"
      ) { [weak self] binding in
        guard let self = self, self.run?.pending?.id == a.id, self.run?.state == "running",
          self.storageOK
        else { return }
        self.creating = nil
        guard binding.directory == scope,
          var item = self.codex.makeSubmission(
            text: prompt, model: model, effort: a.memberSnapshot?.effort ?? "", mode: "send"),
          item.thread == binding.thread
        else {
          self.fail("scope")
          return
        }
        if self.managed {
          do { item.attachments = try self.codexImages(a)
            guard self.codex.validateModel(model,effort:item.effort,attachments:item.attachments) else {throw TeamError.attachmentUnsupported}
          } catch {self.fail("attachmentUnsupported");return}
        }
        let i = self.run!.attempts.count - 1
        self.run!.attempts[i].thread = binding.thread
        self.run!.attempts[i].clientID = item.id
        do { try self.persist() } catch { return }
        // The run record and the native delivery record share this client ID.
        item.sourceContentHash = a.inputHash
        guard self.codex.acceptSubmission(item) else {
          self.fail("storage")
          return
        }
        self.codex.dispatchNext()
      }
    } catch {
      creating = nil
      fail((error as? TeamError)?.rawValue ?? "scope")
    }
  }
  private func recordActivity(_ rows: [TeamActivity], for a: TeamAttempt) {
    guard run?.pending?.id == a.id, !rows.isEmpty, rows != run?.pending?.activity else { return }
    let i = run!.attempts.count - 1
    run!.attempts[i].activity = rows
    try? persist()
  }
  private func recordCodexActivity(_ a: TeamAttempt, record: CodexSubmission) {
    guard let turn = record.turn, codex.threadID == record.thread else { return }
    let rows: [TeamActivity] = codex.displayOrder.suffix(100).compactMap { id in
      guard let item = codex.displayItems[id], item["twosTurnId"] as? String == turn,
        let kind = item["type"] as? String
      else { return nil }
      let status = item["status"] as? String ?? ""
      var body = ""
      switch kind {
      case "agentMessage":
        guard item["phase"] as? String == "commentary" else { return nil }
        body = item["text"] as? String ?? ""
      case "plan":
        body = (item["steps"] as? [[String: Any]] ?? []).compactMap { $0["step"] as? String }
          .joined(separator: "\n")
      case "commandExecution", "fileChange", "mcpToolCall", "webSearch": break
      default: return nil
      }
      return TeamActivity(key: id, kind: kind, status: status, text: String(body.prefix(1400)))
    }
    recordActivity(rows, for: a)
  }
  private func pollCodex(_ a: TeamAttempt) {
    if let g = usageGeneration, g != codex.transportGeneration {
      checking = false
      usageGeneration = nil
    }
    if !codex.connected {
      if !codex.connecting { fail("codexUnavailable") }
      return
    }
    if creating == a.id && codex.creatingThread { return }
    if a.thread == nil {
      // No client submission was authorized before this durable binding.
      closeAttempt("cancelled")
      return
    }
    guard
      let record = codex.ledger.submissions.first(where: {
        $0.id == (a.clientID ?? a.turn) && $0.thread == a.thread
      })
    else {
      fail("unconfirmed")
      return
    }
    if managed, run?.pending?.id == a.id, a.transportState != record.state, let index = run?.attempts.indices.last {
      run?.attempts[index].transportState = record.state
      do { try persist() } catch { fail("storage"); return }
    }
    recordCodexActivity(a, record: record)
    if ["failed", "rejected", "interrupted", "cancelled"].contains(record.state) {
      closeAttempt(record.state)
      return
    }
    if record.state == "unknown" || codex.uncertain {
      if let deadline = observationDeadline, Date() < deadline {
        if codex.threadID == a.thread, !codex.historyLoading, pollCount.isMultiple(of: 3) {
          codex.reconcileDelivery()
        }
        return
      }
      fail("unconfirmed")
      return
    }
    if record.state == "queued", codex.ledger.paused.contains(record.thread) {
      fail("codexUnavailable")
      return
    }
    if !codex.approvals.isEmpty { notice = "approvalRequired" }
    guard record.state == "completed", let t = record.turn, let text = record.result else { return }
    guard !checking else { return }
    if usageAttempt != a.id {
      usageAttempt = a.id
      usageFirstCheck = Date()
    }
    checking = true
    usageGeneration = codex.transportGeneration
    readCodexModel(record, turn: t) { [weak self] actual in
      guard let self = self else { return }
      self.checking = false
      guard self.run?.pending?.id == a.id else { return }
      if actual == nil, Date().timeIntervalSince(self.usageFirstCheck ?? .distantPast) < 15 {
        return
      }
      self.finish(
        a, text: text, actual: actual, source: actual == nil ? nil : "codex_single_turn_usage",
        thread: record.thread, turn: t)
    }
  }
  private func readCodexModel(
    _ record: CodexSubmission, turn: String, completion: @escaping (String?) -> Void
  ) {
    guard codex.connected, record.turn == turn, record.state == "completed" else {
      completion(nil)
      return
    }
    codex.request("account/usage/read", ["threadId": record.thread]) { [weak self] usage in
      guard let self = self, let model = TeamRun.usageModel(usage, thread: record.thread),
        record.reroutedModel == nil || record.reroutedModel == model
      else {
        completion(nil)
        return
      }
      self.codex.request(
        "thread/turns/list",
        ["threadId": record.thread, "limit": 2, "sortDirection": "desc", "itemsView": "notLoaded"]
      ) { turns in
        let data = turns?["data"] as? [[String: Any]]
        let exact =
          data?.count == 1 && data?.first?["id"] as? String == turn
          && data?.first?["status"] as? String == "completed"
          && turns?["nextCursor"] as? String == nil
        completion(exact ? model : nil)
      }
    }
  }
  private func recheckEvidence(_ id: String, index: Int, check: UUID) {
    guard evidenceCheck == check, storageOK, var r = run, r.id == id,
      r.state == "blocked", r.reason == "identity"
    else { return }
    guard index < r.attempts.count else {
      evidenceCheck = nil
      r.checkModelEvidence()
      run = r
      do {
        try persist()
        if r.state == "awaitingOwner" {
          try export(&r)
          run = r
          try persist()
        }
        notice = r.reason
      } catch { notice = r.state == "awaitingOwner" ? "exportRetry" : "storage" }
      publish()
      return
    }
    let a = r.attempts[index]
    let finish: (String?, String) -> Void = { [weak self] model, source in
      guard let self = self, self.evidenceCheck == check, self.run?.id == id,
        self.run?.attempts[index].id == a.id
      else { return }
      if let model = model, !model.isEmpty {
        self.run?.attempts[index].model = model
        self.run?.attempts[index].source = source
        do { try self.persist() } catch {
          self.evidenceCheck = nil
          self.publish()
          return
        }
      }
      self.recheckEvidence(id, index: index + 1, check: check)
    }
    guard a.model == nil, let turn = a.turn, let thread = a.thread, a.state == "completed" else {
      finish(nil, "")
      return
    }
    if let w = a.web, TeamMember.homes[w.provider] != nil,
      channel(a.role, w.provider).web.url?.absoluteString == thread, w.resolvedURL == thread
    {
      let reviewer = channel(a.role, w.provider)
      var req = w.request(inspectOnly: true)
      req["teamReview"] = true
    if managed {req["allowTeamMode"]=true}
      reviewer.webTransfer(req) { reply in
        guard reply["state"] as? String == "reply", reply["conversationURL"] as? String == thread,
          reply["replyMessage"] as? String == turn, let body = reply["reply"] as? String,
          NativeCodex.digest(Data(body.utf8)) == a.resultHash
        else {
          finish(nil, "")
          return
        }
        finish(reply["reportedModel"] as? String, w.provider.lowercased() + "_message_metadata")
      }
    } else if a.web == nil,
      let record = codex.ledger.submissions.first(where: {
        $0.id == a.clientID && $0.thread == thread
      })
    {
      readCodexModel(record, turn: turn) { finish($0, "codex_single_turn_usage") }
    } else {
      finish(nil, "")
    }
  }
  private func isRoomWebTarget(_ url: URL?, member: TeamMember, home: URL) -> Bool {
    guard let target = NativeWorkbench.restorableURL(url, service: home) else { return false }
    return target.path == home.path || (target.path.isEmpty && home.path == "/") ||
      run?.attempts.contains(where: {
        $0.role == member.role && $0.web?.provider == member.service && $0.web?.resolvedURL == target.absoluteString
      }) == true
  }
  private func dispatchWeb(member: TeamMember, selection: String) {
    let reviewer = channel(member.role, member.service)
    guard var r = run, r.state == "running", r.pending == nil,
      let target = NativeWorkbench.restorableURL(reviewer.web.url, service: reviewer.serviceHome),
      isRoomWebTarget(target, member: member, home: reviewer.serviceHome)
    else {
      fail("reviewerChat")
      return
    }
    do {
      let prompt = try r.prompt()
      let a = try r.begin(prompt)
      var w = WebHandoffReceipt(
        source: "team:" + r.id, message: a.id, text: prompt, hash: a.inputHash,
        provider: member.service,
        targetPane: 0, targetURL: target.absoluteString, binding: r.id)
      r.attempts[r.attempts.count - 1].observedWebSelection = selection
      if managed { w.files=try webImages(a) }
      w.teamWireVersion = 1
      // On ChatGPT the rich editor and its send control can mount separately.
      // Journal a draft-only phase before WebKit can write anything.
      if managed, w.provider == "ChatGPT", (w.files ?? []).isEmpty {
        w.state = "draft"
        w.mayHaveSent = false
        w.dispatchReason = "PREPARING_DRAFT_NO_MESSAGE_SENT"
      }
      r.attempts[r.attempts.count - 1].web = w
      run = r
      try persist()
      observationDeadline = Date().addingTimeInterval(15)
      invokeWeb(a.id, w, inspect: false)
    } catch { fail((error as? TeamError)?.rawValue ?? "storage") }
  }
  private static func conversation(_ url: URL, service: String) -> Bool {
    let prefixes = ["Claude": "/chat/", "ChatGPT": "/c/", "DeepSeek": "/a/chat/s/"]
    guard let prefix = prefixes[service], url.path.hasPrefix(prefix) else { return false }
    let id = String(url.path.dropFirst(prefix.count))
    return id.range(of: #"^[A-Za-z0-9_-]+$"#, options: .regularExpression) != nil
  }
  private func pollReviewer(_ a: TeamAttempt) {
    guard let w = a.web else {
      fail("unconfirmed")
      return
    }
    if !checking { invokeWeb(a.id, w, inspect: true) }
  }
  private func invokeWeb(_ id: String, _ w: WebHandoffReceipt, inspect: Bool, checkDraft: Bool = false, restoreDraft: Bool = false) {
    guard !checking else { return }
    guard let attempt = run?.pending, attempt.id == id, TeamMember.homes[w.provider] != nil else { return }
    let role = attempt.role
    let reviewer = channel(role, w.provider)
    if inspect, let bound = w.resolvedURL,
      NativeWorkbench.restorableURL(reviewer.web.url, service: reviewer.serviceHome)?.absoluteString
        != bound
    {
      if checkDraft { recoveryState = "retainedCheck"; publish() }
      return
    }
    checking = true
    var req = w.request(inspectOnly: inspect)
    req["teamReview"] = true
    if managed {req["allowTeamMode"]=true}
    guard let member = attempt.memberSnapshot ?? run?.members.first(where: { $0.role == role }), member.service == w.provider else { checking = false; return }
    if managed && !inspect {
      do {
        req["files"] = try (w.files ?? []).map { file -> [String:Any] in
          let bytes=try self.checkedBlob(file.id,hash:file.hash)
          return ["id":file.id,"name":file.name,"mime":file.mime,"size":file.size,"hash":file.hash,"base64":bytes.base64EncodedString()]
        }
      } catch {checking=false;fail("attachmentUnsupported");return}
    }
    if checkDraft { req["inspectRetainedDraft"] = true }
    let preparing = !inspect && !restoreDraft && w.dispatchReason == "PREPARING_DRAFT_NO_MESSAGE_SENT"
    if preparing || restoreDraft { req["draftOnly"] = true; req["resumeDraft"] = false }
    if managed && member.model.isEmpty { req["teamWebsiteDefault"] = true }
    req["expectedReviewModel"] = aMemberModel(id) ?? member.model
    req["allowedTeamSelections"] = TeamMember.selectionLabels(aMemberModel(id) ?? member.model, service: member.service)
    reviewer.webTransfer(req) { [weak self] response in
      guard let self = self else { return }
      self.checking = false
      guard let a = self.run?.pending, a.id == id, self.storageOK else { return }
      let i = self.run!.attempts.count - 1
      let state = response["state"] as? String ?? "unknown"
      if preparing, !["sent", "reply", "generation_stopped"].contains(state) {
        if self.run?.stopRequested == true {
          self.closeAttempt("cancelled"); return
        }
        if state == "draft", response["reason"] as? String == "EXACT_DRAFT_CONFIRMED_NO_MESSAGE_SENT" {
          guard self.run?.state == "running" else { return }
          do { try self.submitVerifiedDraft(id, w) } catch { self.fail("storage") }
          return
        }
        if ["unknown", "unsupported", "target_changed", "draft"].contains(state) {
          self.run!.attempts[i].web?.dispatchReason = (response["errorCode"] as? Int)
            .map { "DRAFT_WEBKIT_" + String($0) + "_NO_MESSAGE_SENT" } ?? "DRAFT_NOT_CONFIRMED_NO_MESSAGE_SENT"
          self.fail("reviewerDraft"); return
        }
      }
      if (checkDraft || restoreDraft), self.retainedAttempt?.id != id { return }
      if (checkDraft || restoreDraft), !["sent", "reply", "generation_stopped"].contains(state) {
        self.recoveryStep = id
        switch state {
        case "retained_exact": self.recoveryState = "retainedExact"
        case "draft" where restoreDraft && response["reason"] as? String == "EXACT_DRAFT_CONFIRMED_NO_MESSAGE_SENT":
          self.recoveryState = "retainedExact"
        case "retained_empty" where (w.files ?? []).isEmpty: self.recoveryState = "retainedEmpty"
        case "retained_changed", "draft_conflict": self.recoveryState = "retainedChanged"
        default: self.recoveryState = "retainedCheck"
        }
        self.publish(); return
      }
      if !inspect {
        if let selection = response["selectedAtSend"] as? String, member.acceptsSelection(selection) {
          self.run!.attempts[i].observedWebSelection = selection
        }
        self.run!.attempts[i].web?.state = state
        self.run!.attempts[i].web?.dispatchReason = (response["reason"] as? String)?
          .components(separatedBy: " · ").first.map { String($0.prefix(100)) }
        if let code = response["errorCode"] as? Int {
          self.run!.attempts[i].web?.dispatchReason = "WEBKIT_ERROR_" + String(code)
        }
        self.run!.attempts[i].web?.mayHaveSent = ["sent", "reply", "unknown"].contains(state)
        try? self.persist()
      }
      if let raw = response["conversationURL"] as? String,
        let url = NativeWorkbench.restorableURL(
          URL(string: raw), service: reviewer.serviceHome), url.host == reviewer.serviceHome.host,
        Self.conversation(url, service: w.provider),
        w.resolvedURL == nil || w.resolvedURL == url.absoluteString
      {
        self.run!.attempts[i].web?.resolvedURL = url.absoluteString
      }
      if ["reply", "sent", "generation_stopped"].contains(state),
        let bound = w.resolvedURL, response["conversationURL"] as? String != bound
      {
        self.fail("unconfirmed")
        return
      }
      if (checkDraft || restoreDraft), ["sent","reply"].contains(state),
        self.run?.stopRequested != true {
        self.run!.state = "running"; self.run!.reason = ""; self.notice = ""
        self.run!.attempts[i].web?.state = "sent"
        self.run!.attempts[i].web?.mayHaveSent = true
        self.run!.attempts[i].web?.updatedAt = Date().timeIntervalSince1970
        self.startRoomTimer()
      }
      if response["teamGenerating"] as? Bool == true {
        self.recordActivity(
          [TeamActivity(key: id, kind: "generation", status: "running", text: "")], for: a)
      }
      if state == "reply", let text = response["reply"] as? String,
        let t = response["replyMessage"] as? String,
        let url = self.run!.attempts[i].web?.resolvedURL
      {
        self.finish(
          a, text: text, actual: response["reportedModel"] as? String,
          source: response["reportedModel"] == nil
            ? nil : w.provider.lowercased() + "_message_metadata", thread: url,
          turn: t)
      } else if state == "generation_stopped" {
        self.closeAttempt("interrupted")
      } else if state == "sent"
        && (a.state != "sent" || a.web?.resolvedURL != self.run!.attempts[i].web?.resolvedURL)
      {
        self.run!.attempts[i].state = "sent"
        if !inspect { self.observationDeadline = Date().addingTimeInterval(15) }
        try? self.persist()
      } else if state == "sent" {
        return
      } else if !inspect
        && ["verification", "login", "not_loaded", "busy", "draft_conflict", "provider_limited"]
          .contains(state)
      {
        self.run!.attempts[i].state = "unsent"
        if self.run?.stopRequested == true {
          self.run?.state = "stopped"
          self.run?.reason = "stopped"
        } else {
          self.run?.state = "paused"
          self.run?.reason = self.managed ? (["verification":"webVerification","login":"webLogin","not_loaded":"webComposer","busy":"webBusy","draft_conflict":"webDraft","provider_limited":"webLimit"][state] ?? "webUnavailable") : "reviewerUnavailable"
        }
        try? self.persist()
        self.publish()
      } else if inspect, let limit = self.observationDeadline, Date() < limit {
        return
      } else if !inspect && state == "draft" {
        self.fail("reviewerDraft")
      } else if !inspect || self.run?.state == "running" {
        self.fail(state == "unknown" ? "unconfirmed" : "reviewerUnavailable")
      }
    }
  }
  private func finish(
    _ a: TeamAttempt, text: String, actual: String?, source: String?, thread: String, turn: String
  ) {
    guard var r = run, r.pending?.id == a.id else { return }
    do {
      let previouslyPaused = r.state == "paused"
      if a.web != nil { r.attempts[r.attempts.count - 1].web?.result = text }
      if r.stopRequested == true || r.state == "stopping" {
        r.attempts[r.attempts.count - 1].state = "completed"
        r.attempts[r.attempts.count - 1].resultHash = NativeCodex.digest(Data(text.utf8))
        r.attempts[r.attempts.count - 1].thread = thread
        r.attempts[r.attempts.count - 1].turn = turn
        r.attempts[r.attempts.count - 1].model = actual
        r.attempts[r.attempts.count - 1].source = source
        r.state = "stopped"
        r.reason = "stopped"
      } else {
        try r.receive(
          id: a.id, text: text, actual: actual, source: source, thread: thread, turn: turn)
      }
      if previouslyPaused && r.state == "running" { r.state = "paused" }
      observingWeb = nil
      observationDeadline = nil
      notice = ""
      run = r
      try persist()
      if managed {
        do {
          try publishRoomFiles()
          if a.assignment?.kind=="review",let revision=run?.conversation?.revisions.last {try checkVisibleRevision(revision)}
        } catch {
          let reason=(error as? TeamError)?.rawValue ?? "storage"
          run?.state="paused";run?.reason=reason;notice=reason
          if a.assignment?.kind=="review",reason=="fileConflict",var c=run?.conversation,let i=c.revisions.indices.last {
            c.mismatchedRevision=c.revisions[i].id;c.issue="fileConflict";run?.conversation=c
          }
          try? persist()
        }
        return publish()
      }
      if r.state == "awaitingOwner" {
        do {
          try export(&r)
          run = r
          try persist()
        } catch { notice = "exportRetry" }
      }
    } catch {
      r.state = "blocked"
      r.reason = (error as? TeamError)?.rawValue ?? "invalidReply"
      run = r
      try? persist()
    }
    publish()
  }
  private func closeAttempt(_ outcome: String) {
    guard var r = run, r.pending != nil else { return }
    r.attempts[r.attempts.count - 1].state = outcome
    r.state = r.stopRequested == true || r.state == "stopping" ? "stopped" : "blocked"
    r.reason = outcome
    run = r
    try? persist()
    publish()
  }
  private func stop(reason: String = "stopped") {
    guard var r = run, ["running", "paused"].contains(r.state) else { return }
    observingWeb = nil
    if managed {r.conversation?.queue.removeAll();r.conversation?.held.removeAll();r.conversation?.stoppedByUser=true}
    r.stopRequested = true
    observationDeadline = Date().addingTimeInterval(15)
    r.state = r.pending == nil ? "stopped" : "stopping"
    r.reason = reason
    run = r
    do { try persist() } catch { return }
    guard let a = r.pending else { return }
    if let receipt = a.web {
      let reviewer = channel(a.role, receipt.provider)
      reviewer.web.evaluateJavaScript(
        "window.twosTransferLease=String(Math.random())", in: nil, in: NativeWorkbench.handoffWorld,
        completionHandler: nil)
      // The web stop button is scoped to the exact submitted turn.
      if let w = a.web, let s = w.resolvedURL, let url = URL(string: s) {
        reviewer.web.callAsyncJavaScript(
          "return window.twosProviderDOM?.activityIdentity() || ''", arguments: [:], in: nil,
          in: NativeWorkbench.handoffWorld
        ) { [weak self] result in
          guard let self = self, case .success(let v) = result, let token = v as? String,
            !token.isEmpty,
            self.run?.pending?.id == a.id, self.run?.state == "stopping"
          else { return }
          var request = w.request(inspectOnly: true)
          request["teamReview"] = true
          reviewer.webTransfer(request) { reply in
            guard reply["state"] as? String == "sent", reply["teamActivity"] as? String == token
            else { return }
            reviewer.stopFromCompanion(
              url: url, activity: token,
              stillBound: { self.run?.pending?.id == a.id && self.run?.state == "stopping" }
            ) { _ in }
          }
        }
      }
    } else if let thread = a.thread, thread == codex.threadID, let client = a.clientID ?? a.turn,
      client == codex.activeSubmission
    {
      codex.interrupt()
    } else if a.thread == nil {
      creating = nil
      closeAttempt("cancelled")
    }
  }
  private func checkDelivery(_ files: [String: String], folder: CodexDirectory, name: String) throws
  {
    for (filename, body) in files {
      guard
        try NativeCodex.readArtifact(name + "/" + filename, directory: folder).1 == Data(body.utf8)
      else { throw TeamError.wrongVersion }
    }
  }
  private func freeze(_ version: TeamVersion, run: TeamRun) throws -> URL {
    let name = run.frozenName(version.number)
    let work = try TeamFiles.workFolder(for: run)
    do { try TeamFiles.export(version.files, to: work, name: name) } catch TeamError
      .alreadyExported
    { try checkDelivery(version.files, folder: work, name: name) }
    return URL(fileURLWithPath: work.path).appendingPathComponent(name)
  }
  private func export(_ r: inout TeamRun) throws {
    let name = r.deliveryName
    let files = try r.delivery()
    do { try TeamFiles.export(files, to: r.folder, name: name) } catch TeamError.alreadyExported {
      try checkDelivery(files, folder: r.folder, name: name)
    }
    r.exported = URL(fileURLWithPath: r.folder.path).appendingPathComponent(name).path
  }
}

extension TeamWorkspace {
  // A pre-dispatch check may inspect only the exact queued assignment. An
  // uncertain send is handled exclusively by the existing receipt reconciler.
  private var recoveryTarget: (step: TeamAssignment, member: TeamMember)? {
    guard let r = run, r.state == "paused", r.pending == nil, r.stopRequested != true,
      let c = r.conversation, !c.stoppedByUser,
      ["reviewerUnavailable", "reviewerChanged", "codexUnavailable", "webLogin", "webLoading",
       "webUnavailable", "webVerification", "webComposer", "webSelection", "webMismatch",
       "webBusy", "webLimit", "webDraft", "reviewerChat"].contains(r.reason) else { return nil }
    let step = r.retryableUnsentAssignment ?? c.queue.first
    guard let step, let member = r.members.first(where: { $0.role == step.member }) else { return nil }
    return (step, member)
  }
  private var retainedAttempt: TeamAttempt? {
    guard let r = run, r.state == "paused", r.stopRequested != true,
      let a = r.pending, let w = a.web, w.state == "draft", w.mayHaveSent == false,
      w.message == a.id, w.binding == r.id, w.source == "team:" + r.id,
      let m = a.memberSnapshot, m.service == w.provider,
      r.members.contains(where: { $0.role == m.role && $0.service == m.service }),
      w.hash == a.inputHash, NativeCodex.digest(Data(w.text.utf8)) == a.inputHash else { return nil }
    return a
  }

  func restoreEmptyDraft(_ id: String) throws {
    guard let a = retainedAttempt, a.id == id, let w = a.web, !checking,
      recoveryStep == id, recoveryState == "retainedEmpty", (w.files ?? []).isEmpty
    else { throw TeamError.wrongVersion }
    recoveryState = "checkingConnection"; publish()
    invokeWeb(id, w, inspect: false, restoreDraft: true)
  }

  func retryRetainedDraft(_ id: String) throws {
    guard let a = retainedAttempt, a.id == id, let w = a.web, !checking,
      recoveryStep == id, recoveryState == "retainedExact" else { throw TeamError.wrongVersion }
    try submitVerifiedDraft(id, w)
  }

  private func submitVerifiedDraft(_ id: String, _ receipt: WebHandoffReceipt) throws {
    guard run?.pending?.id == id, run?.stopRequested != true, !checking else { throw TeamError.wrongVersion }
    var w = receipt
    w.dispatchReason = nil
    // Persist uncertainty before the website can receive a click, including across a crash.
    w.resumeDraft = true
    w.mayHaveSent = true
    w.updatedAt = Date().timeIntervalSince1970
    w.state = "sending"
    observingWeb = nil
    recoveryState = ""; recoveryStep = ""; notice = ""
    run!.attempts[run!.attempts.count - 1].web = w
    run!.state = "running"; run!.reason = ""
    try persist()
    observationDeadline = Date().addingTimeInterval(15)
    invokeWeb(id, w, inspect: false)
    startRoomTimer(); publish()
  }
  var roomRecovery: [String: Any] {
    if let a = retainedAttempt, let w = a.web {
      return ["step":a.id, "member":a.role, "provider":w.provider, "retained":true,
              "state":recoveryStep == a.id ? recoveryState : "retainedDraft"]
    }
    guard let t = recoveryTarget else { return [:] }
    let current = recoveryStep == t.step.id && checkedMember == t.member
    return ["step": t.step.id, "member": t.member.role, "provider": t.member.service,
            "state": current && !recoveryState.isEmpty ? recoveryState : run!.reason,
            "checked": current ? recoveryChecked : 0,
            "duplicates": run?.conversation?.queuedCopies(of: t.step).count ?? 0]
  }

  private func inspectRoomWebsite(_ member: TeamMember, done: @escaping (String, String) -> Void) {
    let key = channelKey(member.role, member.service)
    let pane = channel(member.role, member.service)
    if pane.web.url == nil && !pane.web.isLoading {
      prepareChannel(member.role, member.service)
    }
    guard let url = pane.web.url else { done("webLoading", ""); return }
    let home = pane.serviceHome
    let authHosts = ["ChatGPT":["auth.openai.com","auth0.openai.com"], "Claude":["platform.claude.com"]]
    let authPath = url.path.split(separator:"/").contains { ["auth","login","signin","sign_in","signup"].contains($0.lowercased()) }
    if url.scheme == "https", let host = url.host,
       (host == home.host && authPath || (authHosts[member.service] ?? []).contains(host) && (authPath || member.service == "ChatGPT")) {
      done("webLogin", ""); return
    }
    guard url.scheme == home.scheme, url.host == home.host, url.port == home.port,
          url.user == nil, url.password == nil else { done("webUnavailable", ""); return }
    pane.web.callAsyncJavaScript("return window.twosProviderDOM?.teamConnection?.(true) || {}",
      arguments: [:], in: nil, in: NativeWorkbench.handoffWorld) { [weak self, weak pane] reply in
      guard let self, let pane, self.channels[key] === pane, pane.web.url == url,
            case .success(let raw) = reply, let observation = raw as? [String: Any],
            let status = observation["state"] as? String else { done(pane?.web.isLoading == true ? "webLoading" : "webUnavailable", ""); return }
      if ["webReady","webDefault"].contains(status), !self.isRoomWebTarget(url, member: member, home: home) {
        done("reviewerChat", ""); return
      }
      let model = observation["model"] as? String ?? ""
      if status == "webReady" {
        guard !model.isEmpty, model.utf8.count <= 160 else { done("webSelection", ""); return }
        done(member.model.isEmpty || member.acceptsSelection(model) ? "webReady" : "webMismatch", model)
      } else if status == "webDefault" {
        done(member.model.isEmpty ? "webReady" : "webSelection", "")
      } else {
        done(["webLogin","webVerification","webComposer","webSelection","webBusy","webLimit","webDraft"].contains(status) ? status : "webUnavailable", "")
      }
    }
  }

  func checkRoomConnection(step: String) throws {
    if let a = retainedAttempt, a.id == step, let w = a.web {
      guard !checking else { return }
      restoreReviewer(w, role: a.role)
      recoveryState = "checkingConnection"; recoveryStep = step; notice = ""; publish()
      invokeWeb(step, w, inspect: true, checkDraft: true)
      return
    }
    guard let target = recoveryTarget, target.step.id == step else { throw TeamError.wrongVersion }
    if recoveryProbe != nil, recoveryStep == step, checkedMember == target.member { return }
    let token = UUID(), member = target.member
    checkedMember = member
    recoveryProbe = token; recoveryStep = step; recoveryState = "checkingConnection"; recoveryChecked = 0
    notice = ""; publish()
    func finish(_ state: String) {
      guard self.recoveryProbe == token else { return }
      self.recoveryProbe = nil
      guard let live = self.recoveryTarget, live.step.id == step, live.member == member else {
        self.recoveryState = ""; self.publish(); return
      }
      self.recoveryState = state; self.recoveryChecked = Date().timeIntervalSince1970
      self.publish()
    }
    let deadline = Date().addingTimeInterval(18)
    func probe() {
      guard self.recoveryProbe == token, let current = self.recoveryTarget,
            current.step.id == step, current.member == member else { finish("webUnavailable"); return }
      if member.service == "Codex" {
        if self.codex.connected {
          let model = member.model.isEmpty
            ? (self.codex.modelCatalog.first(where: { $0["isDefault"] as? Bool == true }) ?? self.codex.modelCatalog.first)?["model"] as? String
            : member.model
          let ready = model.map { self.codex.modelIDs.contains($0) } == true
          finish(ready ? "webReady" : "codexUnavailable"); return
        }
        if !self.codex.connecting { finish("codexUnavailable"); return }
      } else {
        self.inspectRoomWebsite(member) { status, _ in
          guard self.recoveryProbe == token else { return }
          if status == "webLoading", Date() < deadline {
            DispatchQueue.main.asyncAfter(deadline: .now()+0.4) { probe() }
          } else { finish(status) }
        }
        return
      }
      DispatchQueue.main.asyncAfter(deadline: .now()+0.4) { probe() }
    }
    if member.service == "Codex", !codex.connected, !codex.connecting { codex.connectSelectedPane() }
    DispatchQueue.main.asyncAfter(deadline: .now()+18) { [weak self] in
      if self?.recoveryProbe == token { finish(member.service == "Codex" ? "codexUnavailable" : "webUnavailable") }
    }
    probe()
  }

  func continueRoomConnection(step: String, skipCopies: Bool) throws {
    guard let t = recoveryTarget, t.step.id == step, recoveryStep == step,
          checkedMember == t.member, recoveryState == "webReady", recoveryProbe == nil else { throw TeamError.wrongVersion }
    if skipCopies {
      try changeRoom { r in r.conversation?.skipQueuedCopies(of: t.step) }
    }
    try resumeRoom()
  }

  var roomNotice:String {notice}
  var availableModels:[[String:Any]] {codex.modelCatalog}
  func aMemberModel(_ id:String)->String? {run?.attempts.last(where:{$0.id==id})?.memberSnapshot?.model}
  func setupRoom(_ r:TeamRun) throws {
    guard managed,storageOK,run==nil,r.conversation != nil else {throw TeamError.storage}
    run=r;try persist()
  }
  func changeRoom(_ body:(inout TeamRun)throws->Void)throws {
    guard managed,storageOK,var r=run else{throw TeamError.storage}
    try body(&r);run=r;try persist();publish()
  }
  func adoptWebSelection(_ id: String) {
    guard let current = run, let member = current.members.first(where: { $0.role == id }),
      member.service != "Codex" else { return }
    inspectModel(id, member.service) { [weak self] value in
      guard let self, self.run?.id == current.id, self.run?.members.first(where: { $0.role == id }) == member else { return }
      guard !value.isEmpty, value.utf8.count <= 160 else { self.notice = "reviewerUnavailable"; self.publish(); return }
      do {
        try self.changeRoom { r in
          var roster = r.members
          guard let i = roster.firstIndex(of: member) else { throw TeamError.wrongVersion }
          roster[i].model = value
          roster[i].effort = nil
          try r.updateChatRoster(roster)
        }
        self.notice = ""
      } catch { self.notice = (error as? TeamError)?.rawValue ?? "storage" }
      self.publish()
    }
  }
  private func attachRoomReturn(to window: NSWindow?, member: String) {
    guard let window else { return }
    let label = translate("Back") == "Back" ? "Back to chat · Check connection" : "返回群聊并检查连接"
    let button: NSButton
    if let existing = window.titlebarAccessoryViewControllers.compactMap({ $0.view as? NSButton })
      .first(where: { $0.action == #selector(returnFromMember(_:)) }) {
      button = existing
    } else {
      button = NSButton(title: label, target: self, action: #selector(returnFromMember(_:)))
      let accessory = NSTitlebarAccessoryViewController()
      accessory.layoutAttribute = .right
      accessory.view = button
      window.addTitlebarAccessoryViewController(accessory)
    }
    button.title = label
    button.identifier = NSUserInterfaceItemIdentifier(member)
    button.sizeToFit()
  }
  @objc private func returnFromMember(_ sender: NSButton) {
    showRoom?()
    if let a = retainedAttempt, a.role == sender.identifier?.rawValue {
      try? checkRoomConnection(step: a.id)
    } else if let t = recoveryTarget, t.member.role == sender.identifier?.rawValue {
      try? checkRoomConnection(step: t.step.id)
    }
  }
  func openMember(_ id:String) {
    guard let m=run?.members.first(where:{$0.role==id}) else{return}
    if m.service=="Codex" {
      if !codex.connected && !codex.connecting {codex.connectSelectedPane()}
      startRoomTimer()
      if codexWindow==nil {
        let w=NSWindow(contentRect:NSRect(x:0,y:0,width:800,height:620),styleMask:[.titled,.closable,.resizable],backing:.buffered,defer:false)
        w.isReleasedWhenClosed=false;w.contentView=codex.web;codexWindow=w
      }
      attachRoomReturn(to: codexWindow, member: id)
      codexWindow?.title="AI Team · Codex";codexWindow?.makeKeyAndOrderFront(nil)
    } else {
      prepareChannel(id,m.service)
      let w=channel(id,m.service);w.window?.title="TWOS · "+(m.displayName ?? id)+" · "+m.service
      attachRoomReturn(to: w.window, member: id)
      w.showWindow(nil);w.window?.makeKeyAndOrderFront(nil)
    }
  }
  func startRoomTimer() {
    guard managed,timer==nil,storageOK else{return}
    let t=Timer(timeInterval:1,repeats:true){[weak self] _ in self?.tick()}
    timer=t;RunLoop.main.add(t,forMode:.common)
  }
  func stopRoom() {
    guard var r=run else{return}
    recoveryProbe = nil; recoveryState = ""; recoveryStep = ""; awaitingSelection = nil; notice = ""
    if r.pending != nil || ["running","paused"].contains(r.state) {stop();publish();return}
    r.conversation?.queue=[];r.conversation?.stoppedByUser=true;r.state="stopped";r.stopRequested=true;r.reason="stopped"
    run=r;try? persist();publish()
  }
  func resumeRoom()throws {
    guard var r=run,let c=r.conversation else{throw TeamError.storage}
    recoveryState = ""; recoveryStep = ""; recoveryProbe = nil; recoveryChecked = 0
    notice = ""; awaitingSelection = nil
    if let a=r.pending {
      if let w=a.web {restoreReviewer(w,role:a.role);observingWeb=a.id;r.state="paused"}
      else {
        if !codex.connected {if !codex.connecting {codex.connect()};throw TeamError.unavailable}
        if let thread=a.thread {if thread != codex.threadID {codex.selectThread(thread)} else if codex.uncertain {codex.reconcileDelivery()}}
        r.state=r.stopRequested==true ? "stopping":"running"
      }
      observationDeadline=Date().addingTimeInterval(15);notice="reconciling"
    } else {
      guard !c.stoppedByUser else{throw TeamError.wrongVersion}
      if let assignment = r.retryableUnsentAssignment {
        r.conversation?.queue.insert(assignment,at:0);run=r;try persist()
      } else if r.state=="blocked" && c.queue.isEmpty {
        throw TeamError.invalidReply
      }
      if r.reason=="codexUnavailable",!codex.connected,!codex.connecting {codex.connectSelectedPane()}
      try publishRoomFiles()
      r=run ?? r
      if let c=r.conversation,let v=c.revisions.last,c.mismatchedRevision==v.id {
        try checkVisibleRevision(v);r.conversation?.mismatchedRevision=nil
        if ["fileConflict","changedDirectory"].contains(c.issue ?? "") {r.conversation?.issue=nil}
      }
      r.selectNextChatStep()
    }
    run=r;try persist();startRoomTimer();publish()
  }
  private func prepareRoomStep(_ r:inout TeamRun,member:TeamMember)->Bool {
    guard let c=r.conversation, let step=c.queue.first else{fail("wrongVersion");return false}
    do {
      if step.kind=="review" {
        try publishRoomFiles()
        guard let v=run?.conversation?.revisions.last, v.digest==step.frozen else{throw TeamError.wrongVersion}
        try checkVisibleRevision(v)
        r=run ?? r
      }
    } catch {fail((error as? TeamError)?.rawValue ?? "storage");return false}
    if member.service=="Codex" {
      if !codex.connected {
        if !codex.connecting {
          if codex.connectionError.isEmpty {codex.connectSelectedPane()} else {fail("codexUnavailable")}
        }
        return false
      }
      if member.model.isEmpty {
        guard let row=codex.modelCatalog.first(where:{$0["isDefault"] as? Bool==true}) ?? codex.modelCatalog.first,
          let m=row["model"] as? String, !m.isEmpty,let i=r.members.firstIndex(where:{$0.role==member.role}) else{
          fail("codexUnavailable");return false
        }
        r.members[i].model=m;run=r;try? persist();return false
      }
      do {
        let attachments=try imageAttachments(message:step.message)
        guard codex.validateModel(member.model,effort:member.effort ?? "",attachments:attachments) else{
          fail(attachments.isEmpty ? "codexUnavailable":"attachmentUnsupported");return false
        }
      } catch {fail("attachmentUnsupported");return false}
    } else {
      // All managed web work checks the current member window before creating
      // an intent. Reading the visible picker is independent of having a login.
      let key = r.id + "/" + step.id
      if awaitingSelection?.member != key {
        awaitingSelection = (key, Date()); notice = "checkingConnection"; publish()
      }
      if let wait = awaitingSelection, Date().timeIntervalSince(wait.since) >= 18 {
        recoveryProbe = nil; awaitingSelection = nil; fail("webUnavailable"); return false
      }
      if recoveryProbe != nil { return false }
      let token = UUID()
      recoveryProbe = token
      inspectRoomWebsite(member) { [weak self] status, selection in
        guard let self, self.recoveryProbe == token else { return }
        self.recoveryProbe = nil
        guard var live = self.run, live.state == "running", live.pending == nil,
              live.conversation?.queue.first?.id == step.id,
              live.members.first(where: { $0.role == member.role }) == member else { return }
        if status == "webLoading" { return }
        self.awaitingSelection = nil
        guard status == "webReady" else { self.fail(status); return }
        var chosen = member
        if chosen.model.isEmpty && !selection.isEmpty,
           let i = live.members.firstIndex(where: { $0.role == member.role }) {
          chosen.model = selection; live.members[i] = chosen; self.run = live
          do { try self.persist() } catch { self.fail("storage"); return }
        }
        self.notice = ""
        self.dispatchWeb(member: chosen, selection: selection)
      }
      return false
    }
    return true
  }
  func validateForAcceptance(_ v: TeamFileRevision) throws {
    do { try checkVisibleRevision(v) }
    catch let problem as TeamError where problem == .fileConflict || problem == .changedDirectory {
      try changeRoom { r in
        r.conversation?.mismatchedRevision = v.id
        r.conversation?.issue = problem.rawValue
        r.state = "paused"
        r.reason = problem.rawValue
      }
      throw problem
    }
  }
  func checkVisibleRevision(_ v:TeamFileRevision)throws {
    guard let c=run?.conversation else{throw TeamError.storage}
    if v.files.isEmpty{return}
    guard let f=c.output else{throw TeamError.outputNeeded}
    for (name,text) in v.files {
      guard let file=c.ownedFiles[name],file.hash==NativeCodex.digest(Data(text.utf8)) else {throw TeamError.fileConflict}
      _=try TeamArtifacts.visible(name,owner:file,in:f)
    }
  }
  func publishRoomFiles()throws {
    guard var r=run,var c=r.conversation,let v=c.revisions.last,!v.files.isEmpty else{return}
    guard let output=c.output else{throw TeamError.outputNeeded}
    if c.publishedRevision==v.id {return}
    func record()throws {r.conversation=c;run=r;try persist()}
    if let intent=c.writeIntent {
      try TeamArtifacts.commit(intent,in:output);c.ownedFiles[intent.path]=intent.file;c.writeIntent=nil;try record()
    }
    for (n,body) in v.files.sorted(by:{$0.key<$1.key}) {
      if let old=c.ownedFiles[n],old.hash==NativeCodex.digest(Data(body.utf8)) {
        _=try TeamArtifacts.visible(n,owner:old,in:output);continue
      }
      let intent=try TeamArtifacts.stage(body,path:n,in:output,previous:c.ownedFiles[n])
      c.writeIntent=intent;try record()
      try TeamArtifacts.commit(intent,in:output)
      c.ownedFiles[n]=intent.file;c.writeIntent=nil;try record()
    }
    c.publishedRevision=v.id;try record()
  }
  private func executionScratch()throws->CodexDirectory {
    guard let uuid=run?.id,UUID(uuidString:uuid) != nil else{throw TeamError.storage}
    // Foundation can retain Darwin's /var alias. Resolve the existing system
    // temporary root before applying the same strict no-symlink ancestry check.
    guard let real=realpath(FileManager.default.temporaryDirectory.path,nil) else{throw TeamError.changedDirectory}
    let temp=URL(fileURLWithPath:String(cString:real),isDirectory:true);free(real)
    let p=temp.appendingPathComponent("twos-team-turns-"+uuid,isDirectory:true)
    try NativeWorkbench.safeDirectory(p)
    let info=try nativePathMetadata(p.path)
    guard info.st_uid==getuid(),info.st_mode & 0o077==0 else{throw TeamError.changedDirectory}
    return try NativeCodex.inspectDirectory(p.path,isolated:true)
  }
  private func checkedBlob(_ id:String,hash:String)throws->Data {
    guard UUID(uuidString:id) != nil else{throw TeamError.attachmentUnsupported}
    let data=try WebTransferFile.read(directory.appendingPathComponent("attachments/"+id))
    guard NativeCodex.digest(data)==hash else{throw TeamError.wrongVersion}
    return data
  }
  private func images(_ a:TeamAttempt)->[TeamAttachmentRef] {
    guard let step=a.assignment,let c=run?.conversation else{return []}
    return c.inputs.first(where:{$0.id==step.message})?.attachments.filter{$0.mime.hasPrefix("image/")} ?? []
  }
  private func codexImages(_ a:TeamAttempt)throws->[CodexAttachment] {
    guard let step=a.assignment else{return []}
    return try imageAttachments(message:step.message)
  }
  private func imageAttachments(message:String)throws->[CodexAttachment] {
    let files=run?.conversation?.inputs.first(where:{$0.id==message})?.attachments.filter{$0.mime.hasPrefix("image/")} ?? []
    return try files.map {f in let d=try checkedBlob(f.id,hash:f.hash)
      return CodexAttachment(id:f.id,name:f.name,mime:f.mime,base64:d.base64EncodedString(),transportVersion:3,coverage:"image_full",sourceBytes:f.size,sourceHash:f.hash)}
  }
  private func webImages(_ a:TeamAttempt)throws->[WebTransferFile] {
    try images(a).map {f in _=try checkedBlob(f.id,hash:f.hash)
      return WebTransferFile(id:f.id,name:f.name,mime:f.mime,size:f.size,hash:f.hash,source:"team:"+a.id)}
  }
}

extension TeamWorkspace {
  func steerIfBound(_ key:String)throws {
    guard managed,var r=run,var c=r.conversation,r.state=="running",!c.stoppedByUser,
      let active=r.pending,active.memberSnapshot?.service=="Codex",
      ["coordinate","direct","consult","build"].contains(active.assignment?.kind ?? ""),
      let input=c.inputs.first(where:{$0.id==key}),input.attachments.isEmpty,
      let q=c.queue.firstIndex(where:{$0.message==key && $0.member==active.role}),
      let thread=active.thread,thread==codex.threadID,let turn=codex.turnID,
      codex.controlledThreads.contains(thread),!codex.uncertain,!codex.stopRequested,
      let source=codex.ledger.submissions.first(where:{$0.id==active.clientID && $0.id==codex.activeSubmission && $0.thread==thread && $0.turn==turn}),
      codex.draftAttachments.isEmpty,c.supplements?.contains(where:{$0.member==active.role && $0.message==key}) != true,
      let item=codex.makeSubmission(text:input.text,model:source.model,effort:source.effort,mode:"steer")
    else{return}
    let entry=TeamSupplement(message:key,member:active.role,attempt:active.id,thread:thread,turn:turn,client:item.id,state:"intent")
    c.queue.remove(at:q);c.supplements=(c.supplements ?? [])+[entry];r.conversation=c;run=r;try persist()
    guard codex.acceptSubmission(item) else {
      fail("unconfirmed");return
    }
    codex.steer(item);refreshSupplements()
  }
  private func refreshSupplements() {
    guard var r=run,var c=r.conversation,var list=c.supplements else{return}
    var changed=false
    for i in list.indices where ["intent","queued","sending","accepted","unknown"].contains(list[i].state) {
      let s=list[i]
      guard let native=codex.ledger.submissions.first(where:{$0.id==s.client && $0.thread==s.thread && ($0.turn==s.turn || $0.turn==nil)})
      else{continue}
      if list[i].state != native.state {list[i].state=native.state;changed=true}
    }
    if changed {c.supplements=list;r.conversation=c;run=r;try? persist();publish()}
  }
}
