import AppKit
import UniformTypeIdentifiers
import WebKit

/// Owns the selected view. Each active room has its own journal, Codex client,
/// website views, cancellation state and timer inside TeamWorkspace.
final class TeamChatWorkspace: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
  let web: WKWebView
  let resources: URL, preferences: URL, directory: URL
  private let page: URL, translate: (String) -> String
  var leftSelection: (@escaping (String, String, String) -> Void) -> Void = { done in
    done("Codex", "", "")
  }
  private var sessions: [String: TeamWorkspace] = [:]
  private var importedPreviews: Bool {
    FileManager.default.fileExists(
      atPath: directory.appendingPathComponent("include-previews").path)
  }
  private var records: [String: TeamRun] = [:], legacy: [String: TeamRun] = [:]
  private var selected = "", error = "", ready = false, shown = false, storageLock: Int32 = -1
  private var indexed = false, awaitingPresentation = false, importing = false
  private var processing = Set<String>(), opening = false
  private var lastPayload: Data?, refresh: DispatchWorkItem?, observer: NSObjectProtocol?
  private var previewWindow: NSWindow?
  private let previewNavigation = TeamPreviewNavigation()
  init(root: URL, preferences: URL, translate: @escaping (String) -> String) {
    self.resources = root
    self.preferences = preferences
    self.translate = translate
    directory = preferences.appendingPathComponent("team-r2")
    page = root.appendingPathComponent("ai_team/index.html")
    let config = WKWebViewConfiguration()
    config.websiteDataStore = .nonPersistent()
    web = WKWebView(frame: .zero, configuration: config)
    super.init()
    do {
      try NativeWorkbench.safeDirectory(directory)
      let fd = open(
        directory.appendingPathComponent("lock").path, O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC,
        0o600)
      guard fd >= 0 else { throw TeamError.storage }
      guard flock(fd, LOCK_EX | LOCK_NB) == 0 else {
        close(fd)
        throw TeamError.busy
      }
      storageLock = fd
      loadLibrary()

    } catch { self.error = (error as? TeamError)?.rawValue ?? "storage" }
    config.userContentController.add(self, name: "teamChat")
    web.navigationDelegate = self
    web.loadFileURL(page, allowingReadAccessTo: page.deletingLastPathComponent())
    observer = NotificationCenter.default.addObserver(
      forName: NSApplication.willTerminateNotification, object: nil, queue: .main
    ) { [weak self] _ in self?.shutdown() }
  }
  private var previewDirectories: [URL] {
    let support =
      preferences.lastPathComponent == "Tianma Work OS Preferences"
      ? preferences.deletingLastPathComponent()
      : FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(
        "Library/Application Support")
    return ["TWOS AI Team Acceptance", "TWOS AI Team R1 Preview"].map {
      support.appendingPathComponent($0 + "/team-r1")
    }
  }
  private static func index(_ directory: URL, rooms: Bool) -> ([String: TeamRun], Bool) {
    guard FileManager.default.fileExists(atPath: directory.path) else { return ([:], false) }
    guard let attrs = try? nativePathMetadata(directory.path), attrs.st_uid == getuid(),
      attrs.st_mode & S_IFMT == S_IFDIR,
      directory.resolvingSymlinksInPath().standardizedFileURL.path
        == directory.standardizedFileURL.path,
      let urls = try? FileManager.default.contentsOfDirectory(
        at: directory, includingPropertiesForKeys: nil)
    else { return ([:], true) }
    var runs: [String: TeamRun] = [:]
    var failed = false
    for url in urls {
      let id = rooms ? url.lastPathComponent : url.deletingPathExtension().lastPathComponent
      guard UUID(uuidString: id) != nil, rooms || url.pathExtension == "json" else { continue }
      if rooms {
        guard let info = try? nativePathMetadata(url.path), info.st_mode & S_IFMT == S_IFDIR,
          info.st_uid == getuid()
        else {
          failed = true
          continue
        }
      }
      do { runs[id] = try TeamWorkspace.readRecord(id, from: rooms ? url : directory) } catch {
        failed = true
      }
    }
    return (runs, failed)
  }
  private func loadLibrary() {
    let current = directory
    let old =
      [preferences.appendingPathComponent("team-r1")] + (importedPreviews ? previewDirectories : [])
    DispatchQueue.global(qos: .userInitiated).async { [weak self] in
      let (records, err) = Self.index(current, rooms: true)
      var legacy: [String: TeamRun] = [:]
      var failed = err
      for dir in old {
        let (found, err) = Self.index(dir, rooms: false)
        legacy.merge(found) { first, _ in first }
        failed = failed || err
      }
      let id = try? String(contentsOf: current.appendingPathComponent("selected"), encoding: .utf8)
      DispatchQueue.main.async {
        guard let self, self.storageLock >= 0 else { return }
        self.records = records
        self.legacy = legacy
        self.indexed = true
        if failed { self.error = "archiveError" }
        if let id, records[id] != nil || legacy[id] != nil { self.selected = id }
        if self.awaitingPresentation { self.present() } else { self.publish() }
      }
    }
  }
  private func importPreviews() {
    guard !importing else { return }
    importing = true
    let dirs = previewDirectories
    DispatchQueue.global(qos: .utility).async { [weak self] in
      var runs: [String: TeamRun] = [:]
      var failed = false
      for dir in dirs {
        let (values, err) = Self.index(dir, rooms: false)
        runs.merge(values) { first, _ in first }
        failed = failed || err
      }
      DispatchQueue.main.async {
        guard let self, self.storageLock >= 0 else { return }
        self.importing = false
        self.legacy.merge(runs) { original, _ in original }
        if failed { self.error = "archiveError" }
        self.publish()
      }
    }
  }
  var hasActiveCodexTurn: Bool { sessions.values.contains(where: { $0.hasActiveCodexTurn }) }
  func shutdown() {
    refresh?.cancel()
    refresh = nil
    if let o = observer {
      NotificationCenter.default.removeObserver(o)
      observer = nil
    }
    for session in sessions.values {
      session.roomChanged = nil
      session.shutdown()
    }
    sessions = [:]
    web.configuration.userContentController.removeScriptMessageHandler(forName: "teamChat")
    if storageLock >= 0 {
      close(storageLock)
      storageLock = -1
    }
  }
  func present() {
    awaitingPresentation = true
    guard indexed else {
      publish()
      return
    }
    if !shown, storageLock >= 0 {
      shown = true
      if selected.isEmpty {
        newRoom()
      } else {
        do { try select(selected) } catch { self.error = "storage" }
      }
      // Restore dispatch ownership by room, without replaying queued/unknown turns.
      for id in records.keys.sorted()
      where ["running", "stopping"].contains(records[id]?.state ?? "") {
        do { _ = try session(id) } catch { self.error = "storage" }
      }
    }
    publish()
  }
  private func session(_ id: String) throws -> TeamWorkspace {
    guard storageLock >= 0, UUID(uuidString: id) != nil else { throw TeamError.storage }
    if let s = sessions[id] { return s }
    let s = TeamWorkspace(
      root: resources, preferences: directory.appendingPathComponent(id), translate: translate,
      managed: true, initialRecord: records[id])
    s.roomChanged = { [weak self, weak s] in
      guard let self, let s, let r = s.run, self.sessions[id] === s else { return }
      self.records[id] = r
      self.schedulePublish()
    }
    sessions[id] = s
    if let r = s.run { records[id] = r }
    return s
  }
  private func schedulePublish() {
    guard refresh == nil else { return }
    let work = DispatchWorkItem { [weak self] in
      self?.refresh = nil
      self?.publish()
    }
    refresh = work
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.06, execute: work)
  }
  private func select(_ id: String) throws {
    guard storageLock >= 0, records[id] != nil || legacy[id] != nil else { throw TeamError.storage }
    try Data(id.utf8).write(to: directory.appendingPathComponent("selected"), options: .atomic)
    selected = id
    error = ""
    if records[id] != nil {
      _ = try session(id)
    } else if let old = legacy[id] {
      try makeRoom(id: id, service: "Codex", model: "", effort: "", old: old)
      return
    }
    publish()
  }
  private func makeRoom(
    id: String, service: String, model: String, effort: String, old: TeamRun? = nil
  ) throws {
    let s = try session(id)
    let dir = directory.appendingPathComponent(id)
    guard s.run == nil else { throw TeamError.busy }
    var info = stat()
    guard lstat(dir.path, &info) == 0, info.st_mode & S_IFMT == S_IFDIR else {
      throw TeamError.storage
    }
    let f = CodexDirectory(
      path: dir.path, device: UInt64(info.st_dev), inode: UInt64(info.st_ino), isolated: true)
    let requested = TeamMember.services.contains(service) ? service : "Codex"
    var members = [
      TeamMember(
        role: "Planner", product: requested, provider: TeamMember.providers[requested]!,
        model: model, displayName: "Ada", duties: ["Planner"],
        effort: requested == "Codex" ? effort : nil),
      TeamMember(
        role: "Builder", product: "Codex", provider: "OpenAI", model: "", displayName: "Kai",
        duties: ["Builder"]),
      TeamMember(
        role: "Reviewer", product: "Claude", provider: "Anthropic", model: "", displayName: "Ren",
        duties: ["Reviewer"]),
    ]
    var c = TeamConversation()
    if let old {
      members = old.members
      for i in members.indices {
        members[i].displayName =
          members[i].displayName ?? TeamConversation.displayName(members[i].role)
        members[i].duties = [members[i].role]
      }
      c.legacyID = old.id
      c.stoppedByUser = old.stopRequested == true || old.state == "stopped"
      // The original journal stays intact, including unconfirmed actions and Owner decisions.
      c.legacyContext = try TeamFiles.json([
        "goal": old.goal, "state": old.state, "ownerDecision": old.owner,
        "sharedMessages": try TeamFiles.json((old.messages ?? []).filter(\.share).map(\.text)),
        "lastPublicReply": old.attempts.last(where: { $0.state == "completed" })?.replyText ?? "",
        "lastFiles": try TeamFiles.json(old.versions.last?.files ?? [:]),
        "lastReview": old.versions.last?.review?.findings.en ?? "",
      ])
      if old.pending != nil {
        c.issue = "legacyUnconfirmed"
        c.stoppedByUser = true
      }
    }
    var r = TeamRun(
      id: id, created: old?.created ?? Date().timeIntervalSince1970, goal: old?.goal ?? "", csv: "",
      folder: f, members: members)
    r.conversation = c
    r.state = "draft"
    r.next = ""
    try s.setupRoom(r)
    records[id] = r
    try select(id)
  }
  private func newRoom() {
    guard !opening, storageLock >= 0 else { return }
    opening = true
    leftSelection { [weak self] service, model, effort in
      guard let self else { return }
      self.opening = false
      do {
        try self.makeRoom(id: UUID().uuidString, service: service, model: model, effort: effort)
      } catch { self.error = "storage" }
      self.publish()
    }
  }
  private func editable(_ id: String) throws -> TeamWorkspace {
    guard id == selected else { throw TeamError.wrongVersion }
    if records[id] == nil, let old = legacy[id] {
      try makeRoom(id: id, service: "Codex", model: "", effort: "", old: old)
    }
    return try session(id)
  }
  func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
    ready = true
    lastPayload = nil
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
  private func archiveEntries(_ old: TeamRun?) -> [[String: Any]] {
    guard let old else { return [] }
    var rows: [[String: Any]] = [
      ["member": "Owner", "state": "goal", "text": old.goal, "time": old.created]
    ]
    rows += (old.messages ?? []).map {
      [
        "member": "Owner", "state": $0.share ? "sent" : "privateNote", "text": $0.text,
        "time": $0.time,
      ]
    }
    rows += old.attempts.map { a in
      [
        "member": old.members.first(where: { $0.role == a.role })?.displayName ?? a.role,
        "state": a.state, "text": a.replyText ?? "", "time": a.started,
      ]
    }
    return rows
  }
  func publish() {
    guard ready else { return }
    let all = legacy.merging(records) { _, new in new }
    let rooms = all.values.sorted { $0.created > $1.created }.map {
      ["id": $0.id, "title": $0.goal, "state": $0.state]
    }
    var data: [String: Any] = [
      "zh": translate("Back") != "Back", "id": selected, "rooms": rooms, "error": error,
      "writable": storageLock >= 0 && indexed,
    ]
    if let r = all[selected] {
      let c = r.conversation
      data["room"] =
        [
          "id": r.id, "goal": r.goal, "state": r.state, "reason": r.reason, "old": c == nil,
          "members": jsonObject(r.members), "draft": jsonObject(c?.draft ?? TeamDraft()),
          "language": c?.language ?? "auto", "inputs": jsonObject(c?.inputs ?? []),
          "answers": jsonObject(c?.answers ?? []),
          "undelivered": jsonObject(c?.undelivered ?? []),
          "rosterChanges": jsonObject(c?.rosterChanges ?? []), "plans": jsonObject(c?.plans ?? []),
          "pending": r.pending?.id ?? "",
          "attempts": r.attempts.map { a in
            [
              "id": a.id, "member": a.role, "snapshot": jsonObject(a.memberSnapshot),
              "state": a.state, "transport": a.transportState ?? "",
              "requested": a.memberSnapshot?.model ?? "", "actual": a.model ?? "",
              "text": a.replyText ?? "", "time": a.started, "message": a.assignment?.message ?? "",
              "kind": a.assignment?.kind ?? a.role,
              "activity": jsonObject(a.activity ?? []),
            ] as [String: Any]
          },
          "supplements": jsonObject(c?.supplements ?? []), "queue": jsonObject(c?.queue ?? []),
          "issue": c?.issue ?? "", "stop": c?.stoppedByUser ?? false,
          "path": c?.output?.path ?? "", "files": c?.ownedFiles.keys.sorted() ?? [],
          "mismatch": c?.mismatchedRevision ?? "",
          "currentFiles": c?.revisions.last?.files.keys.sorted() ?? [],
          "updated": c?.revisions.last?.time ?? 0, "revision": c?.revisions.last?.id ?? "",
          "verdict": c?.revisions.last?.verdict ?? "",
          "accepted": c?.revisions.last?.acceptedAt != nil, "legacy": c?.legacyID ?? "",
          "historyRows": archiveEntries(c == nil ? r : c?.legacyID.flatMap { legacy[$0] }),
          "processing": processing.contains(selected),
          "catalog": sessions[selected]?.availableModels ?? [],
          "channelNotice": sessions[selected]?.roomNotice ?? "",
        ] as [String: Any]
    }
    guard let bytes = try? JSONSerialization.data(withJSONObject: data, options: .sortedKeys),
      bytes != lastPayload
    else { return }
    lastPayload = bytes
    web.callAsyncJavaScript(
      "window.renderTeam(state)", arguments: ["state": data], in: nil, in: .page,
      completionHandler: nil)
  }
  private func jsonObject<T: Encodable>(_ object: T) -> Any {
    guard let d = try? TeamFiles.bytes(object),
      let value = try? JSONSerialization.jsonObject(with: d, options: .fragmentsAllowed)
    else { return NSNull() }
    return value
  }
  func userContentController(
    _ controller: WKUserContentController, didReceive message: WKScriptMessage
  ) {
    guard storageLock >= 0, indexed, message.webView === web, message.frameInfo.isMainFrame,
      message.frameInfo.request.url?.standardizedFileURL == page.standardizedFileURL,
      let args = message.body as? [String: Any], let action = args["action"] as? String
    else { return }
    do {
      if action == "new" {
        newRoom()
        return
      }
      if action == "import" {
        try Data().write(to: directory.appendingPathComponent("include-previews"), options: .atomic)
        importPreviews()
        publish()
        return
      }
      guard let id = args["id"] as? String, UUID(uuidString: id) != nil else {
        throw TeamError.wrongVersion
      }
      if action == "select" {
        try select(id)
        return
      }
      let s = try editable(id)
      error = ""
      switch action {
      case "draft", "send":
        guard let key = args["key"] as? String, UUID(uuidString: key) != nil,
          let body = args["text"] as? String,
          body.utf8.count <= 32000, let recipients = args["recipients"] as? [String]
        else { throw TeamError.invalidInput }
        try s.changeRoom { r in
          guard var c = r.conversation else { throw TeamError.storage }
          if let prior = c.inputs.first(where: { $0.id == key }) {
            if action == "send",
              prior.text != body.trimmingCharacters(in: .whitespacesAndNewlines)
                || prior.recipients != recipients
            {
              throw TeamError.wrongVersion
            }
            return
          }
          guard c.draft.key == key else { throw TeamError.wrongVersion }
          c.draft.text = body
          c.draft.recipients = recipients
          if action == "send" {
            guard !processing.contains(id) else { throw TeamError.busy }
            try c.submit(c.draft, members: r.members, language: c.language)
            if r.goal.isEmpty {
              r.goal = String(
                (body.isEmpty ? c.inputs.last?.attachments.first?.name ?? "" : body).prefix(100))
            }
            r.conversation = c
            if r.pending == nil && r.state != "stopping" {
              r.stopRequested = false
              r.selectNextChatStep()
            }
          } else {
            r.conversation = c
          }
        }
        if action == "send" {
          s.startRoomTimer()
          try s.steerIfBound(key)
        }
      case "language":
        guard let x = args["language"] as? String, ["auto", "zh-CN", "en"].contains(x) else {
          throw TeamError.invalidInput
        }
        try s.changeRoom { $0.conversation?.language = x }
      case "roster":
        let members = try JSONDecoder().decode(
          [TeamMember].self,
          from: JSONSerialization.data(withJSONObject: args["members"] ?? NSNull()))
        try s.changeRoom { try $0.updateChatRoster(members) }
        if s.run?.state == "running" { s.startRoomTimer() }
      case "adoptSelection": if let m = args["member"] as? String { s.adoptWebSelection(m) }
      case "channel": if let m = args["member"] as? String { s.openMember(m) }
      case "directory": selectFolder(for: s)
      case "attach": chooseFiles(for: s)
      case "upload":
        guard args["key"] as? String == s.run?.conversation?.draft.key else {
          throw TeamError.wrongVersion
        }
        guard let parts = args["files"] as? [[String: String]], parts.count <= 8 else {
          throw TeamError.invalidInput
        }
        let rows = try parts.map { item -> (String, Data) in
          guard let name = item["name"], let b = item["bytes"], b.count <= 11_000_000,
            let bytes = Data(base64Encoded: b)
          else { throw TeamError.attachmentUnsupported }
          return (name, bytes)
        }
        try importAttachments(rows, session: s)
      case "detach":
        guard args["key"] as? String == s.run?.conversation?.draft.key else {
          throw TeamError.wrongVersion
        }
        guard let attachment = args["attachment"] as? String else { throw TeamError.invalidInput }
        guard
          let ref = s.run?.conversation?.draft.attachments.first(where: { $0.id == attachment }),
          UUID(uuidString: attachment) != nil
        else { throw TeamError.wrongVersion }
        try s.changeRoom {
          $0.conversation?.draft.attachments.removeAll(where: { $0.id == attachment })
        }
        if s.run?.conversation?.inputs.contains(where: { $0.attachments.contains(ref) }) == false {
          let url = directory.appendingPathComponent(id + "/attachments/" + attachment)
          if let bytes = try? WebTransferFile.read(url), NativeCodex.digest(bytes) == ref.hash {
            try FileManager.default.removeItem(at: url)
          }
        }
      case "stop": s.stopRoom()
      case "reconcile": try s.resumeRoom()
      case "file", "openFolder", "attachment": try fileAction(args, session: s)
      case "accept":
        guard let r = s.run, r.pending == nil, r.state == "awaitingOwner",
          let v = r.conversation?.revisions.last,
          v.id == args["version"] as? String, v.verdict == "approve"
        else { throw TeamError.wrongVersion }
        try s.validateForAcceptance(v)
        try s.changeRoom { run in
          guard var c = run.conversation, let last = c.revisions.indices.last else {
            throw TeamError.wrongVersion
          }
          c.revisions[last].acceptedAt = Date().timeIntervalSince1970
          run.conversation = c
          run.state = "accepted"
        }
      default: return
      }
    } catch { self.error = (error as? TeamError)?.rawValue ?? "storage" }
    publish()
  }
}

extension TeamChatWorkspace {
  private func selectFolder(for session: TeamWorkspace) {
    guard let window = web.window, let id = session.run?.id else { return }
    let panel = NSOpenPanel()
    panel.canChooseFiles = false
    panel.canChooseDirectories = true
    panel.canCreateDirectories = true
    panel.prompt = translate("Back") == "Back" ? "Use this folder" : "使用此目录"
    if session.run?.conversation?.output != nil {
      panel.message =
        translate("Back") == "Back"
        ? "Keep existing files where they are and publish this task’s current files in the selected folder."
        : "原有文件保留在原目录。此任务的当前成果将写入所选目录。"
    }
    panel.beginSheetModal(for: window) { [weak self, weak session] response in
      guard response == .OK, let url = panel.url, let self, let session,
        self.sessions[id] === session
      else { return }
      do {
        let folder = try NativeCodex.inspectDirectory(url.path, isolated: false)
        try session.changeRoom { r in
          guard var c = r.conversation else { throw TeamError.storage }
          if let earlier = c.output, earlier != folder {
            let saved = TeamOutputBinding(
              folder: earlier, files: c.ownedFiles, revision: c.publishedRevision,
              time: Date().timeIntervalSince1970, unsettled: c.writeIntent)
            c.earlierOutputs = (c.earlierOutputs ?? []) + [saved]
            c.ownedFiles = [:]
            c.writeIntent = nil
            c.publishedRevision = nil
          }
          c.output = folder
          r.conversation = c
        }
        try session.publishRoomFiles()
        if ["outputNeeded", "fileConflict", "changedDirectory"].contains(session.run?.reason ?? ""),
          session.run?.stopRequested != true
        {
          try session.resumeRoom()
        }
      } catch { self.error = (error as? TeamError)?.rawValue ?? "changedDirectory" }
      self.publish()
    }
  }

  private func chooseFiles(for session: TeamWorkspace) {
    guard let window = web.window, let key = session.run?.conversation?.draft.key else { return }
    let panel = NSOpenPanel()
    panel.allowsMultipleSelection = true
    panel.canChooseDirectories = false
    panel.allowedContentTypes = CodexAttachmentParser.extensions.compactMap {
      UTType(filenameExtension: $0)
    }
    panel.beginSheetModal(for: window) { [weak self, weak session] response in
      guard response == .OK, let self, let session else { return }
      let urls = panel.urls
      self.enqueueAttachments(session: session, key: key) {
        guard urls.count <= 8 else { throw CodexAttachmentFailure.tooLarge }
        var total = 0
        return try urls.map { url in
          let bytes = try WebTransferFile.read(url)
          total += bytes.count
          guard total <= 12_000_000 else { throw CodexAttachmentFailure.tooLarge }
          return (url.lastPathComponent, bytes)
        }
      }
    }
  }
  private func importAttachments(_ rows: [(String, Data)], session: TeamWorkspace) throws {
    guard let key = session.run?.conversation?.draft.key else { throw TeamError.storage }
    enqueueAttachments(session: session, key: key) { rows }
  }

  private func enqueueAttachments(
    session: TeamWorkspace, key: String, load: @escaping () throws -> [(String, Data)]
  ) {
    guard let room = session.run?.id else { return }
    guard !processing.contains(room) else {
      error = "busy"
      publish()
      return
    }
    let root = directory.appendingPathComponent(room).appendingPathComponent("attachments")
    let work = DispatchQueue.global(qos: .userInitiated)
    processing.insert(room)
    publish()
    work.async {
      var created: [URL] = []
      do {
        try NativeWorkbench.safeDirectory(root)
        var bytesRead = 0
        var refs: [TeamAttachmentRef] = []
        for (name, bytes) in try load() {
          guard !name.isEmpty, name.count <= 255, !(name as NSString).isAbsolutePath,
            (name as NSString).lastPathComponent == name, !name.contains("\\"),
            name.rangeOfCharacter(from: .controlCharacters) == nil
          else { throw CodexAttachmentFailure.malformed }
          bytesRead += bytes.count
          guard bytesRead <= 12_000_000 else { throw CodexAttachmentFailure.tooLarge }
          let a = try CodexAttachmentParser.parse(name: name, bytes: bytes, scratch: root)
          let id = UUID().uuidString
          let file = root.appendingPathComponent(id)
          try bytes.write(to: file, options: .withoutOverwriting)
          created.append(file)
          refs.append(
            TeamAttachmentRef(
              id: id, name: name, mime: a.mime, hash: a.sourceHash, size: bytes.count,
              text: a.mime.hasPrefix("image/") ? nil : String(decoding: a.bytes, as: UTF8.self)))
        }
        DispatchQueue.main.async {
          defer {
            self.processing.remove(room)
            self.publish()
          }
          do {
            try session.changeRoom { r in
              guard var c = r.conversation, c.draft.key == key else { throw TeamError.wrongVersion }
              let items = c.draft.attachments + refs
              guard items.count <= 8, items.reduce(0, { $0 + $1.size }) <= 12_000_000 else {
                throw CodexAttachmentFailure.tooLarge
              }
              c.draft.attachments = items
              r.conversation = c
            }
          } catch {
            // A persist failure can leave the renamed journal visible. Keep blobs it might reference.
            if (error as? TeamError) != .storage {
              for f in created { try? FileManager.default.removeItem(at: f) }
            }
            self.error =
              (error as? CodexAttachmentFailure)?.rawValue ?? (error as? TeamError)?.rawValue
              ?? "storage"
          }
        }
      } catch {
        for f in created { try? FileManager.default.removeItem(at: f) }
        DispatchQueue.main.async {
          self.processing.remove(room)
          self.error = (error as? CodexAttachmentFailure)?.rawValue ?? "attachmentUnsupported"
          self.publish()
        }
      }
    }
  }
  private func fileAction(_ args: [String: Any], session: TeamWorkspace) throws {
    guard let r = session.run, let c = r.conversation else { throw TeamError.storage }
    if args["action"] as? String == "attachment" {
      guard let id = args["attachment"] as? String, UUID(uuidString: id) != nil,
        let f = (c.draft.attachments + c.inputs.flatMap(\.attachments)).first(where: { $0.id == id }
        )
      else { throw TeamError.wrongVersion }
      let data = try WebTransferFile.read(
        directory.appendingPathComponent(r.id + "/attachments/" + id))
      guard NativeCodex.digest(data) == f.hash else { throw TeamError.wrongVersion }
      showPreview(
        name: f.name, text: f.text, image: f.mime.hasPrefix("image/") ? NSImage(data: data) : nil)
      return
    }
    guard let folder = c.output,
      try NativeCodex.inspectDirectory(folder.path, isolated: folder.isolated) == folder
    else { throw TeamError.changedDirectory }
    if args["action"] as? String == "openFolder" {
      guard NSWorkspace.shared.open(URL(fileURLWithPath: folder.path)) else {
        throw TeamError.changedDirectory
      }
      return
    }
    guard let name = args["path"] as? String, let owner = c.ownedFiles[name] else {
      throw TeamError.wrongVersion
    }
    let u = try TeamArtifacts.visible(name, owner: owner, in: folder)
    switch args["mode"] as? String {
    case "reveal": NSWorkspace.shared.activateFileViewerSelecting([u])
    case "open":
      // A model-generated executable or application must never be launched by the artifact button.
      if ["html", "htm", "md", "txt", "csv", "tsv", "json", "pdf", "png", "jpg", "jpeg"].contains(
        u.pathExtension.lowercased())
      {
        guard NSWorkspace.shared.open(u) else { throw TeamError.unavailable }
      } else {
        NSWorkspace.shared.open(
          [u], withApplicationAt: URL(fileURLWithPath: "/System/Applications/TextEdit.app"),
          configuration: NSWorkspace.OpenConfiguration()
        ) { [weak self] _, err in
          if err != nil {
            DispatchQueue.main.async {
              self?.error = "unavailable"
              self?.publish()
            }
          }
        }
      }
    case "preview":
      let bytes = try TeamArtifacts.verifiedContents(name, owner: owner, in: folder)
      let body = String(decoding: bytes, as: UTF8.self)
      if ["html", "htm"].contains(u.pathExtension.lowercased()) {
        showHTMLPreview(name: name, body: body)
      } else {
        showPreview(name: name, text: body, image: nil)
      }
    default: throw TeamError.invalidInput
    }
  }
  private func showHTMLPreview(name: String, body: String) {
    let config = WKWebViewConfiguration()
    config.websiteDataStore = .nonPersistent()
    config.defaultWebpagePreferences.allowsContentJavaScript = false
    let view = WKWebView(frame: .zero, configuration: config)
    // Render only the verified bytes. No connector, task bridge, network or script access.
    let policy =
      "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'; frame-src 'none'\">"
    view.navigationDelegate = previewNavigation
    view.loadHTMLString(policy + body, baseURL: nil)
    showPreview(name: name, text: "", image: nil)
    previewWindow?.contentView = view
  }
  private func showPreview(name: String, text: String?, image: NSImage?) {
    let window =
      previewWindow
      ?? NSWindow(
        contentRect: NSRect(x: 0, y: 0, width: 680, height: 480),
        styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
    window.isReleasedWhenClosed = false
    window.title = name
    if let image {
      let view = NSImageView()
      view.image = image
      view.imageScaling = .scaleProportionallyUpOrDown
      window.contentView = view
    } else {
      let scroll = NSScrollView()
      scroll.hasVerticalScroller = true
      let body = NSTextView()
      body.isEditable = false
      body.isRichText = false
      body.string = text ?? ""
      body.textContainerInset = NSSize(width: 16, height: 14)
      body.autoresizingMask = [.width]
      scroll.documentView = body
      window.contentView = scroll
    }
    if previewWindow == nil { window.center() }
    previewWindow = window
    window.makeKeyAndOrderFront(nil)
  }
}

private final class TeamPreviewNavigation: NSObject, WKNavigationDelegate {
  func webView(
    _ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
    decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
  ) {
    decisionHandler(
      action.targetFrame?.isMainFrame == true && action.navigationType == .other
        && action.request.url?.absoluteString == "about:blank" ? .allow : .cancel)
  }
}
