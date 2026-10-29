import AppKit
import Foundation
import LocalAuthentication
import WebKit
import Darwin

// Security checks need inode/type/permission metadata, not extended attributes.
// FileManager.attributesOfItem also reads xattrs and can stall the main thread
// on protected ancestors. lstat preserves the no-symlink boundary and normal OS
// access checks without touching unrelated attributes or file contents.
func nativePathMetadata(_ path: String) throws -> stat {
    var value = stat()
    guard lstat(path, &value) == 0 else { throw POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO) }
    return value
}

// Shared presentation used by the real launcher and layout/lifecycle tests.
// Sheets do not block the main dispatch callback that owns pipe/exit events.
final class RecoveryPrompt {
    private(set) var alert: NSAlert?
    private(set) var fields: [NSSecureTextField] = []

    static func passwordAccessory(_ labels: [String]) -> (NSView, [NSSecureTextField]) {
        let view = NSView(frame: NSRect(x: 0, y: 0, width: 420, height: 76))
        let fields = labels.enumerated().map { index, label -> NSSecureTextField in
            let field = NSSecureTextField(frame: NSRect(x: 0, y: index == 0 ? 44 : 0, width: 420, height: 30))
            field.autoresizingMask = [.width]
            field.placeholderString = label
            field.setAccessibilityLabel(label)
            field.isEditable = true; field.isSelectable = true
            view.addSubview(field)
            return field
        }
        fields[0].nextKeyView = fields[1]
        return (view, fields)
    }

    func show(on window: NSWindow, title: String, detail: String, action: String,
              cancel: String, passwordLabels: [String] = [],
              completion: @escaping (NSApplication.ModalResponse, [String]) -> Void) {
        dismiss()
        let sheet = NSAlert(); sheet.messageText = title; sheet.informativeText = detail
        sheet.addButton(withTitle: action); sheet.addButton(withTitle: cancel)
        if !passwordLabels.isEmpty {
            let (view, inputs) = Self.passwordAccessory(passwordLabels)
            sheet.accessoryView = view; fields = inputs
            sheet.window.initialFirstResponder = inputs.first
        }
        alert = sheet
        sheet.beginSheetModal(for: window) { [weak self, weak sheet] response in
            guard let self = self, let sheet = sheet, self.alert === sheet else { return }
            let values = self.fields.map { $0.stringValue }
            self.fields.forEach { $0.stringValue = "" }
            self.fields = []; self.alert = nil
            completion(response, values)
        }
    }

    func dismiss() {
        guard let sheet = alert else { return }
        alert = nil
        fields.forEach { $0.stringValue = "" }; fields = []
        if let parent = sheet.window.sheetParent { parent.endSheet(sheet.window, returnCode: .abort) }
        sheet.window.orderOut(nil)
    }
}

// Official pages own their UI, authentication, models, limits and conversations.
// This browser never reads cookies, intercepts responses or reconstructs chats.
final class NativeWorkbench: NSWindowController, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate, WKScriptMessageHandler {
    static let home = URL(string: "https://chatgpt.com/")!
    let web: WKWebView
    let paneView: NSView
    let preferences: URL
    let translate: (String) -> String
    let openProjects: () -> Void
    let address = NSTextField(labelWithString: "https://chatgpt.com")
    let notice = NSTextField(wrappingLabelWithString: "")
    private var noticeMessage = ""
    let progress = NSProgressIndicator()
    var observations: [NSKeyValueObservation] = []
    var popups: [NativeWorkbench] = []
    var downloads: [WKDownload] = []
    var backButton: NSButton!
    var forwardButton: NSButton!
    var profilePersistent = true
    var isPopup: Bool
    var handoffHandler: ((String, URL) -> Void)?
    var targetBinding = ""
    var targetProvider = "Codex"
    var navigationChanged: (() -> Void)?
    var navigationReady: (() -> Void)?
    var handoffButton: NSButton!
    let handoffResources: URL?
    var instructionHandler: ((String, URL, String) -> Void)?
    var retryHandler: ((String, URL) -> Void)?
    var inspectHandler: ((String, URL) -> Void)?
    var handoffReady: (() -> Void)?
    var discussResult: ((String) -> Void)?
    var sendWebReply: ((String, URL) -> Void)?
    var chooseFiles: (() -> Void)?
    var clearFiles: (() -> Void)?
    var fileButton: NSButton?
    var fileSelectionCount = 0
    static let handoffWorld = WKContentWorld.world(name: "TWOS explicit instruction handoff")
    let serviceHome: URL
    var locationKey: String

    // Retain only official conversation locations; discard queries and fragments
    // so OAuth codes, session tokens and external destinations are never saved.
    static func restorableURL(_ url: URL?, service: URL = home) -> URL? {
        guard let url = url, url.scheme == service.scheme, url.host == service.host,
              url.user == nil, url.password == nil, url.port == service.port,
              (url.host != "chatgpt.com" || url.path.range(of: "^/(?:c/[A-Za-z0-9-]+|g/[A-Za-z0-9_/-]+)?/?$", options: .regularExpression) != nil),
              !url.path.split(separator: "/").contains(where: { ["auth", "oauth", "callback", "login", "signin", "sign_in", "signup", "sign_up", "api"].contains(String($0).lowercased()) })
        else { return nil }
        var clean = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        clean.query = nil; clean.fragment = nil
        return clean.url
    }

    static func safeDirectory(_ directory: URL) throws {
        var cursor = directory
        while cursor.path != "/" {
            do {
                let attrs = try nativePathMetadata(cursor.path)
                if attrs.st_mode & S_IFMT == S_IFLNK { throw CocoaError(.fileWriteNoPermission) }
            } catch let error as POSIXError where error.code == .ENOENT {
                // A new child may not exist yet; existing ancestors still checked.
            }
            cursor.deleteLastPathComponent()
        }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
    }

    static func save(_ value: [String: String], at file: URL) throws {
        try safeDirectory(file.deletingLastPathComponent())
        // Atomic replacement cannot follow an existing file symlink.
        try JSONSerialization.data(withJSONObject: value).write(to: file, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
    }

    init(preferences: URL, translate: @escaping (String) -> String,
         openProjects: @escaping () -> Void, configuration: WKWebViewConfiguration? = nil, serviceHome: URL = NativeWorkbench.home, locationKey: String = "official-browser-location.json", handoffResources: URL? = nil) {
        self.preferences = preferences; self.translate = translate; self.openProjects = openProjects
        self.serviceHome = serviceHome; self.locationKey = locationKey
        self.handoffResources = handoffResources ?? Bundle.main.resourceURL?.appendingPathComponent("engine/_internal/static_cockpit")
        isPopup = configuration != nil
        let config = configuration ?? WKWebViewConfiguration()
        if configuration == nil {
            do {
                try Self.safeDirectory(preferences)
                let profileName = serviceHome.host == "chatgpt.com" ? "official-browser-profile.json" : "browser-profile-" + Data((serviceHome.host ?? "website").utf8).base64EncodedString().replacingOccurrences(of: "/", with: "_") + ".json"
                let file = preferences.appendingPathComponent(profileName)
                let saved = (try? Data(contentsOf: file)).flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: String] }
                let identifier = saved?["identifier"].flatMap(UUID.init(uuidString:)) ?? UUID()
                try Self.save(["identifier": identifier.uuidString], at: file)
                if #available(macOS 14.0, *) { config.websiteDataStore = WKWebsiteDataStore(forIdentifier: identifier) }
                else { config.websiteDataStore = .nonPersistent(); profilePersistent = false }
            } catch { config.websiteDataStore = .nonPersistent(); profilePersistent = false }
        }
        web = WKWebView(frame: .zero, configuration: config)
        let win = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1080, height: 800),
                           styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        win.title = "TWOS · " + (serviceHome.host ?? "Website")
        paneView = win.contentView!
        win.minSize = NSSize(width: 680, height: 540)
        win.isReleasedWhenClosed = false
        super.init(window: win)
        web.navigationDelegate = self; web.uiDelegate = self
        if configuration == nil, ["chatgpt.com", "claude.ai", "chat.deepseek.com", "localhost", "127.0.0.1"].contains(serviceHome.host ?? "") {
            let root = handoffResources ?? Bundle.main.resourceURL?.appendingPathComponent("engine/_internal/static_cockpit")
            if let file = root?.appendingPathComponent("native_codex/handoff.js"), let script = try? String(contentsOf: file, encoding: .utf8) {
                let adapter = (try? String(contentsOf: root!.appendingPathComponent("native_codex/provider_dom.js"), encoding: .utf8)) ?? ""
                let source = adapter + "\n" + script.replacingOccurrences(of: "__TWOS_ZH__", with: translate("Back") != "Back" ? "true" : "false")
                config.userContentController.add(self, contentWorld: Self.handoffWorld, name: "twosHandoff")
                config.userContentController.addUserScript(WKUserScript(source: source, injectionTime: .atDocumentEnd, forMainFrameOnly: true, in: Self.handoffWorld))
            }
        }
        web.allowsBackForwardNavigationGestures = true
        backButton = button("←", #selector(back)); backButton.toolTip = translate("Back")
        forwardButton = button("→", #selector(forward)); forwardButton.toolTip = translate("Forward")
        address.lineBreakMode = .byTruncatingMiddle
        address.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        address.setAccessibilityLabel(translate("Current website"))
        address.isSelectable = true
        let top = NSStackView(views: [backButton, forwardButton, button("↻", #selector(reload)), address,
                                     button("Open in Safari", #selector(openSafari))])
        top.orientation = .horizontal; top.spacing = 10
        handoffButton = button("Handoff to paired pane", #selector(handoff))
        let files=button("Attachments",#selector(selectWebFiles));fileButton=files
        let actions = NSStackView(views: [button("Original TWOS projects", #selector(projects)), files, button("Remove selection",#selector(removeWebFiles)), handoffButton])
        actions.orientation = .horizontal; actions.spacing = 10
        notice.font = .systemFont(ofSize: 12); notice.textColor = .secondaryLabelColor
        notice.isHidden = true
        progress.style = .bar; progress.isIndeterminate = false; progress.minValue = 0; progress.maxValue = 1
        progress.isHidden = true
        let bar = NSStackView(views: [top, actions, notice, progress])
        bar.orientation = .vertical; bar.alignment = .leading; bar.spacing = 8
        bar.edgeInsets = NSEdgeInsets(top: 10, left: 12, bottom: 8, right: 12)
        bar.translatesAutoresizingMaskIntoConstraints = false; web.translatesAutoresizingMaskIntoConstraints = false
        let content = win.contentView!
        content.addSubview(bar); content.addSubview(web)
        NSLayoutConstraint.activate([
            bar.topAnchor.constraint(equalTo: content.topAnchor), bar.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            bar.trailingAnchor.constraint(equalTo: content.trailingAnchor),
            top.widthAnchor.constraint(equalTo: bar.widthAnchor, constant: -24),
            notice.widthAnchor.constraint(equalTo: bar.widthAnchor, constant: -24),
            progress.widthAnchor.constraint(equalTo: bar.widthAnchor, constant: -24), progress.heightAnchor.constraint(equalToConstant: 2),
            web.topAnchor.constraint(equalTo: bar.bottomAnchor), web.leadingAnchor.constraint(equalTo: content.leadingAnchor),
            web.trailingAnchor.constraint(equalTo: content.trailingAnchor), web.bottomAnchor.constraint(equalTo: content.bottomAnchor)])
        observations = [web.observe(\.estimatedProgress, options: [.new]) { [weak self] _, _ in self?.updateNavigation() },
                        web.observe(\.isLoading, options: [.new]) { [weak self] _, _ in self?.updateNavigation() },
                        web.observe(\.url, options: [.new]) { [weak self] _, _ in self?.updateNavigation() }]
        win.center()
        if !profilePersistent { showNotice("This browser session cannot be saved here. Use Open in Safari to keep your login.") }
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    func button(_ title: String, _ action: Selector) -> NSButton {
        let button = NSButton(title: translate(title), target: self, action: action)
        button.bezelStyle = .rounded; button.identifier = NSUserInterfaceItemIdentifier(title); return button
    }
    func refreshLanguage() {
        func walk(_ view: NSView) {
            if let button = view as? NSButton, let key = button.identifier?.rawValue { button.title = translate(key) }
            if view is WKWebView { return }
            view.subviews.forEach(walk)
        }
        walk(paneView)
        setFileSelectionCount(fileSelectionCount)
        updateTarget(provider: targetProvider, binding: targetBinding)
        backButton.toolTip = translate("Back"); forwardButton.toolTip = translate("Forward")
        address.setAccessibilityLabel(translate("Current website"))
        web.evaluateJavaScript("window.twosHandoffLanguage?.(\(translate("Back") != "Back" ? "true" : "false"))", in: nil, in: Self.handoffWorld, completionHandler: nil)
    }
    func setFileSelectionCount(_ count:Int) {
        fileSelectionCount=count
        fileButton?.title=translate("Attachments") + (count>0 ? " (\(count))" : "")
        fileButton?.setAccessibilityLabel(fileButton?.title)
    }
    func showNotice(_ message: String) { noticeMessage=message;notice.stringValue = translate(message); notice.isHidden = false }
    func reconcileAccessNotice(_ state:String) {
        if ["idle","running"].contains(state),noticeMessage=="ChatGPT could not finish loading. Retry with ↻, or open this page in Safari. Your saved work is retained." {
            noticeMessage="";notice.stringValue="";notice.isHidden=true
            return
        }
        let authNotices=["Claude sign-in is available. Sign in on this page; no task has been sent.","Claude is waiting for website verification. No task was sent. Open in Safari is a fallback, not embedded verification success."]
        if ["idle","running"].contains(state),authNotices.contains(noticeMessage) {
            showNotice("Claude input is ready. Handoff sends only the instruction you select.")
        }
    }
    func start(embedded: Bool = false) {
        if !embedded { showWindow(nil) }
        guard web.url == nil else { return }
        let data = try? Data(contentsOf: preferences.appendingPathComponent(locationKey))
        let saved = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: String] }
        let restored = saved?["url"].flatMap(URL.init(string:)).flatMap { Self.restorableURL($0, service: serviceHome) }
        web.load(URLRequest(url: restored ?? serviceHome))
    }
    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { refreshLanguage(); navigationReady?() }
    func updateNavigation() {
        navigationChanged?()
        address.stringValue = web.url.map { ($0.scheme ?? "https") + "://" + ($0.host ?? "") } ?? serviceHome.absoluteString
        backButton.isEnabled = web.canGoBack; forwardButton.isEnabled = web.canGoForward
        progress.doubleValue = web.estimatedProgress; progress.isHidden = !web.isLoading
        if !isPopup, let location = Self.restorableURL(web.url, service: serviceHome) {
            do { try Self.save(["url": location.absoluteString], at: preferences.appendingPathComponent(locationKey)) }
            catch { showNotice("The conversation address could not be saved. Your ChatGPT history remains in your account.") }
        }
    }
    @objc func back() { web.goBack() }
    @objc func forward() { web.goForward() }
    @objc func reload() { if web.url == nil { web.load(URLRequest(url: serviceHome)) } else { web.reload() } }
    @objc func projects() { openProjects() }
    @objc func selectWebFiles() { chooseFiles?() }
    @objc func removeWebFiles() { clearFiles?() }
    @objc func openSafari() {
        let url = Self.restorableURL(web.url, service: serviceHome) ?? serviceHome
        guard let safari = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.apple.Safari") else { return }
        NSWorkspace.shared.open([url], withApplicationAt: safari, configuration: NSWorkspace.OpenConfiguration())
    }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, let source = Self.restorableURL(web.url, service: serviceHome),
              message.frameInfo.request.url?.host == source.host, message.frameInfo.request.url?.scheme == source.scheme,
              message.frameInfo.request.url?.port == source.port, let value = message.body as? [String: Any],
              let raw = value["source"] as? String, Self.restorableURL(URL(string: raw), service: serviceHome) == source else { return }
        if value["action"] as? String == "handoff", let text = value["text"] as? String, text.utf8.count <= 200_000 {
            guard value["targetBinding"] as? String == targetBinding, !targetBinding.isEmpty else { showNotice("The destination changed. Review the current destination and send again."); return }
            instructionHandler?(text, source, value["message"] as? String ?? "")
        } else if value["action"] as? String == "retryHandoff", let id = value["id"] as? String { retryHandler?(id, source) }
        else if value["action"] as? String == "inspectHandoff", let id = value["id"] as? String { inspectHandler?(id, source) }
        else if value["action"] as? String == "ready" { handoffReady?() }
        else if value["action"] as? String == "discuss", let id = value["id"] as? String { discussResult?(id) }
        else if value["action"] as? String == "sendReply", let id = value["id"] as? String { sendWebReply?(id, source) }
    }
    func showHandoffProgress(_ value: [String: Any]) {
        guard let raw = value["source"] as? String, let source = URL(string: raw), Self.restorableURL(web.url, service: serviceHome) == source else { return }
        web.callAsyncJavaScript("if (window.twosHandoffUpdate) await window.twosHandoffUpdate(record);", arguments: ["record": value], in: nil, in: Self.handoffWorld, completionHandler: nil)
    }
    func deliverResult(_ text: String, id: String, source: URL, inspectOnly: Bool = false, completion: @escaping (String) -> Void) {
        guard Self.restorableURL(web.url, service: serviceHome) == source else { completion("pending"); return }
        web.callAsyncJavaScript("return window.twosDeliverResult ? await window.twosDeliverResult(payload) : 'pending';",
            arguments: ["payload": ["id": id, "text": text, "source": source.absoluteString, "inspectOnly": inspectOnly]], in: nil, in: Self.handoffWorld) { result in
                switch result {
                case .success(let state): completion(state as? String ?? "unknown")
                case .failure: completion("unknown")
                }
            }
    }
    static func handoffScript(allowLatestReply: Bool) -> String {
        return """
        (() => {
            const selected = window.getSelection()?.toString();
            if (selected?.trim()) return selected;
            if (!\(allowLatestReply ? "true" : "false")) return '';
            // The official site has used both message-role and Markdown-style
            // attributes. Read only the last rendered answer, excluding hidden
            // variants and reasoning summaries. Unknown layouts fail visibly.
            const replies = [...document.querySelectorAll('[data-message-author-role="assistant"], [data-markdown-text-style="assistant-message"]')]
                .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
            const reply=replies.at(-1);if(!reply)return '';
            const controls=[...reply.querySelectorAll('button,[role="button"],[data-twos-native-card]')].map(el=>[el,el.getAttribute('style')]);
            try{for(const [el,style] of controls)el.setAttribute('style',(style||'')+';display:none!important;');return reply.innerText||'';}
            finally{for(const [el,style] of controls)style===null?el.removeAttribute('style'):el.setAttribute('style',style);}
        })()
        """
    }
    @objc func handoff() {
        guard let source = Self.restorableURL(web.url, service: serviceHome), let handler = handoffHandler else {
            showNotice("Select a destination pane before handing off instructions."); return
        }
        // Read an explicit selection within a complete answer, or the final answer.
        // Floating controls and streaming fragments cannot become instructions.
        let binding = targetBinding
        providerSnapshot(includeReply: true) { [weak self] value in
            guard let self = self else { return }
            guard value["state"] as? String == "reply", let text = value["text"] as? String, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                self.showNotice("No complete reply is available yet. Wait for the reply to finish, then send it. " + (value["reason"] as? String ?? "")); return
            }
            guard self.web.url.flatMap({ Self.restorableURL($0, service: self.serviceHome) }) == source else {
                self.showNotice("The source conversation changed. Review it before handing off again."); return
            }
            guard binding == self.targetBinding, !binding.isEmpty else { self.showNotice("The destination changed. Review the current destination and send again."); return }
            self.notice.isHidden = true
            if let instruction = self.instructionHandler { instruction(text, source, value["message"] as? String ?? "") }
            else { handler(text, source) }
        }
    }
    func providerSnapshot(includeReply: Bool = false, completion: @escaping ([String: Any]) -> Void) {
        guard let source = Self.restorableURL(web.url, service: serviceHome),
              let file = handoffResources?.appendingPathComponent("native_codex/provider_dom.js"),
              let script = try? String(contentsOf: file, encoding: .utf8) else { completion(["state":"unknown","reason":"PAGE_UNAVAILABLE"]); return }
        web.callAsyncJavaScript(script + "\nreturn window.twosProviderDOM?." + (includeReply ? "selectedOrLatest()" : "observe()") + ";", arguments: [:], in: nil, in: Self.handoffWorld) { [weak self] result in
            guard let self = self, Self.restorableURL(self.web.url, service:self.serviceHome) == source else { completion(["state":"unknown","reason":"CONVERSATION_CHANGED"]); return }
            if case .success(let value) = result, let value = value as? [String:Any] { completion(value) }
            else { completion(["state":"unknown","reason":"OBSERVER_UNAVAILABLE"]) }
        }
    }
    func updateTarget(provider: String, binding: String) {
        targetProvider = provider; targetBinding = binding
        let title = provider == "Codex" ? translate("Send to Codex") : translate("Send to") + " " + provider
        handoffButton?.title = title; handoffButton?.setAccessibilityLabel(title)
        web.callAsyncJavaScript("window.twosHandoffTarget?.(target);", arguments: ["target": ["provider": provider, "binding": binding]], in: nil, in: Self.handoffWorld, completionHandler: nil)
    }
    // Invoked only by the trusted host for an explicit transfer or inspection.
    // No credentials, network interception, page-world native bridge or arbitrary command.
    func webTransfer(_ request: [String: Any], completion: @escaping ([String: Any]) -> Void) {
        guard let raw = request["targetURL"] as? String,
              let expected = URL(string: raw), let actual = Self.restorableURL(web.url, service: serviceHome),
              actual == expected || (request["inspectOnly"] as? Bool == true && actual.host == expected.host && actual.scheme == expected.scheme && actual.port == expected.port),
              let file = handoffResources?.appendingPathComponent("native_codex/web_handoff.js"),
              let script = try? String(contentsOf: file, encoding: .utf8) else { completion(["state": "target_changed"]); return }
        web.callAsyncJavaScript(script, arguments: ["request": request], in: nil, in: Self.handoffWorld) { result in
            switch result {
            case .success(let value): completion(value as? [String: Any] ?? ["state": "unknown"])
            case .failure(let error):
                let failure = error as NSError
                // Preserve the actionable script failure in the existing
                // advanced receipt instead of silently labelling it unknown.
                // JavaScript expressions here are shipped code, not evaluated
                // user instructions; bound length and remove URL parameters.
                let detail=(failure.userInfo["WKJavaScriptExceptionMessage"] as? String ?? "WEB_OPERATION_FAILED")
                    .replacingOccurrences(of:"https?://[^\\s]+",with:"[website]",options:.regularExpression)
                completion(["state": "unknown", "errorCode": failure.code,
                            "reason": "WEB_OPERATION_FAILED · \(failure.code) · " + String(detail.prefix(240)),
                            "scriptError": failure.userInfo["WKJavaScriptExceptionMessage"] as? String ?? "WEB_OPERATION_FAILED"])
            }
        }
    }
    func placeDraft(_ text: String, expectedSource: URL, completion: @escaping (Bool) -> Void) {
        guard Self.restorableURL(web.url, service: serviceHome) == expectedSource else {
            showNotice("Return to the original conversation before bringing this result back."); completion(false); return
        }
        // Fill the original composer only after the user's Return Result click.
        // Existing draft text is retained; no site Send button is activated.
        let payload = (try? JSONSerialization.data(withJSONObject: [text])).flatMap { String(data: $0, encoding: .utf8) } ?? "[]"
        let script = #"""
        (() => {
            const text = \#(payload)[0];
            const el = document.querySelector('#prompt-textarea') || document.querySelector('textarea') || document.querySelector('[contenteditable=true][role=textbox]');
            if (!el || !text) return false;
            el.focus();
            if (el instanceof HTMLTextAreaElement) {
                const next = el.value + (el.value ? '\n\n' : '') + text;
                Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(el, next);
                el.dispatchEvent(new Event('input', {bubbles:true}));
                return el.value === next;
            }
            const range = document.createRange(); range.selectNodeContents(el); range.collapse(false);
            const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
            return document.execCommand('insertText', false, (el.innerText.trim() ? '\n\n' : '') + text);
        })()
        """#
        web.evaluateJavaScript(script) { [weak self] value, _ in
            let ok = value as? Bool == true
            self?.showNotice(ok ? "Result added to the original composer. Review it and send in the original interface." : "The website composer could not accept this result. Your result is retained in the other pane.")
            completion(ok)
        }
    }
    static func permitsNavigation(_ url: URL, serviceHome: URL, isSubframe: Bool) -> Bool {
        // srcdoc is an inline child document used by ordinary web content,
        // including security checks. Keep WebKit's origin/sandbox enforcement;
        // it must not become a top-level native-bridge or local-file entry.
        let inlineChild = isSubframe && url.absoluteString == "about:srcdoc"
        let localPage = serviceHome.scheme == "http" && ["127.0.0.1", "localhost", "[::1]"].contains(serviceHome.host ?? "") && url.host == serviceHome.host && url.port == serviceHome.port && url.scheme == "http"
        return url.scheme == "https" || localPage || url.absoluteString == "about:blank" || inlineChild
    }
    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        // Browser navigation cannot execute local files or custom app commands.
        if action.shouldPerformDownload && ["https", "blob"].contains(url.scheme ?? "") { decisionHandler(.download); return }
        guard Self.permitsNavigation(url, serviceHome: serviceHome, isSubframe: action.targetFrame?.isMainFrame == false) else {
            if action.navigationType == .linkActivated {
                showNotice("This link cannot be opened in the ChatGPT browser. Use the original browser for this action.")
            }
            decisionHandler(.cancel); return
        }
        decisionHandler(.allow)
    }
    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        decisionHandler(response.canShowMIMEType ? .allow : .download)
    }
    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { navigationFailed(error) }
    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { navigationFailed(error) }
    func navigationFailed(_ error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { showNotice("ChatGPT could not finish loading. Retry with ↻, or open this page in Safari. Your saved work is retained.") }
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { showNotice("The browser page stopped. Reload with ↻ to return to ChatGPT.") }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        guard action.targetFrame == nil else { return nil }
        let child = NativeWorkbench(preferences: preferences, translate: translate, openProjects: openProjects, configuration: configuration, serviceHome: serviceHome, locationKey: locationKey)
        popups.append(child); child.showWindow(nil)
        return child.web
    }
    func webViewDidClose(_ webView: WKWebView) { close() }
    func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
        guard let window = web.window ?? window else { completionHandler(); return }
        let alert = NSAlert(); alert.messageText = frame.request.url?.host ?? translate("Website message"); alert.informativeText = message
        alert.addButton(withTitle: translate("OK")); alert.beginSheetModal(for: window) { _ in completionHandler() }
    }
    func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
        guard let window = web.window ?? window else { completionHandler(false); return }
        let alert = NSAlert(); alert.messageText = frame.request.url?.host ?? translate("Website message"); alert.informativeText = message
        alert.addButton(withTitle: translate("OK")); alert.addButton(withTitle: translate("Cancel"))
        alert.beginSheetModal(for: window) { response in completionHandler(response == .alertFirstButtonReturn) }
    }
    func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
        guard let window = web.window ?? window else { completionHandler(nil); return }
        let alert = NSAlert(); alert.messageText = frame.request.url?.host ?? translate("Website message"); alert.informativeText = prompt
        let input = NSTextField(frame: NSRect(x: 0, y: 0, width: 360, height: 28)); input.stringValue = defaultText ?? ""; alert.accessoryView = input
        alert.addButton(withTitle: translate("OK")); alert.addButton(withTitle: translate("Cancel"))
        alert.beginSheetModal(for: window) { response in completionHandler(response == .alertFirstButtonReturn ? input.stringValue : nil) }
    }
    @available(macOS 12.0, *)
    func webView(_ webView: WKWebView, requestMediaCapturePermissionFor origin: WKSecurityOrigin, initiatedByFrame frame: WKFrameInfo, type: WKMediaCaptureType, decisionHandler: @escaping (WKPermissionDecision) -> Void) {
        decisionHandler(origin.protocol == "https" && origin.host == "chatgpt.com" ? .prompt : .deny)
    }
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping ([URL]?) -> Void) {
        guard let window = web.window ?? window else { completionHandler(nil); return }
        let panel = NSOpenPanel(); panel.canChooseFiles = true; panel.canChooseDirectories = parameters.allowsDirectories
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.beginSheetModal(for: window) { response in completionHandler(response == .OK ? panel.urls : nil) }
    }
    func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { downloads.append(download); download.delegate = self }
    func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { downloads.append(download); download.delegate = self }
    func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
        guard let window = web.window ?? window else { completionHandler(nil); return }
        let panel = NSSavePanel(); panel.nameFieldStringValue = URL(fileURLWithPath: suggestedFilename).lastPathComponent
        panel.beginSheetModal(for: window) { answer in completionHandler(answer == .OK ? panel.url : nil) }
    }
    func downloadDidFinish(_ download: WKDownload) { downloads.removeAll { $0 === download }; showNotice("Download saved to your chosen location.") }
    func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
        downloads.removeAll { $0 === download }
        if (error as NSError).code != NSURLErrorCancelled {
            showNotice("The download did not finish. Retry from this website.")
        }
    }
}

// The only child runtime is shipped inside this signed app bundle. No shell,
// package manager, downloaded executable, credential copy, or elevated helper.
final class Launcher: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    let status = NSTextField(wrappingLabelWithString: "Preparing Tianma Work OS…")
    let detail = NSTextField(wrappingLabelWithString: "Checking your Mac and bundled runtime.")
    let spinner = NSProgressIndicator()
    var retry: NSButton!
    var openUI: NSButton!
    var prerequisite: NSButton!
    var service: Process?
    var input: Pipe?
    var output: Pipe?
    var readyURL: URL?
    var nativeWorkbench: IntegratedWorkbench?
    var expectedStop = false
    var starting = false
    var errorCode = ""
    var buffer = Data()
    var logURL: URL!
    var diagnosticRoot: String?
    var authProcess: Process?
    var launchID = UUID().uuidString
    var startupStage = "native_launcher"
    var workspaceReview = false
    var diagnosticFields: [String: Any] = [:]
    let environmentPicker = NSPopUpButton(frame: .zero, pullsDown: false)
    let languagePicker = NSPopUpButton(frame: .zero, pullsDown: false)
    var environments: [[String:String]] = []
    var selectedEnvironment: String?
    var preferencesURL: URL!
    var locale = "en-US"
    var translations: [String:[String:String]] = [:]
    var languageTimer: Timer?
    var identityLabel: NSTextField?
    var recoveryButton: NSButton!
    var recoveryProcess: Process?
    var recoveryInput: Pipe?
    var recoveryOutput: Pipe?
    var recoveryBuffer = Data()
    var recoveryActive = false
    var recoveryCompleted = false
    var recoveryReported = false
    var recoveryTimer: DispatchWorkItem?
    var recoveryAuth: LAContext?
    let recoveryPrompt = RecoveryPrompt()
    var recoveryExited = false
    var recoveryEOF = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let args = CommandLine.arguments
        if let index = args.firstIndex(of: "--diagnostic-root"), index + 1 < args.count {
            diagnosticRoot = args[index + 1]
        }
        preferencesURL = diagnosticRoot.map { URL(fileURLWithPath: $0) }
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Tianma Work OS Preferences")
        if let url = Bundle.main.resourceURL?.appendingPathComponent("engine/_internal/static_cockpit/project_first/native_i18n.json"),
           let data = try? Data(contentsOf: url), let value = try? JSONSerialization.jsonObject(with: data) as? [String:[String:String]] { translations = value }
        readLanguage()
        loadEnvironments()
        logURL = diagnosticRoot.map { URL(fileURLWithPath: $0).appendingPathComponent("logs") }
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Tianma Work OS Desktop")
        let menu = NSMenu()
        let appItem = NSMenuItem()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "About Tianma Work OS", action: #selector(about), keyEquivalent: "")
        appMenu.addItem(withTitle: "Quit Tianma Work OS", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu
        menu.addItem(appItem)
        let editItem = NSMenuItem(); let editMenu = NSMenu(title: "Edit")
        for (title, action, key) in [("Cut", #selector(NSText.cut(_:)), "x"), ("Copy", #selector(NSText.copy(_:)), "c"),
                                     ("Paste", #selector(NSText.paste(_:)), "v"), ("Select All", #selector(NSText.selectAll(_:)), "a")] {
            editMenu.addItem(withTitle: title, action: action, keyEquivalent: key)
        }
        editItem.submenu = editMenu; menu.addItem(editItem)
        let windowItem = NSMenuItem(); let windowMenu = NSMenu(title: "Window")
        windowMenu.addItem(withTitle: "Close Window", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")
        windowMenu.addItem(withTitle: "ChatGPT + Codex", action: #selector(openNativeWorkbench), keyEquivalent: "1")
        windowMenu.addItem(withTitle: "Original TWOS projects", action: #selector(showLegacyLauncher), keyEquivalent: "2")
        windowItem.submenu = windowMenu; menu.addItem(windowItem)
        NSApp.mainMenu = menu
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 620),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "Tianma Work OS"
        window.delegate = self
        let title = NSTextField(labelWithString: "Tianma Work OS")
        title.font = .systemFont(ofSize: 28, weight: .semibold)
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "Unknown"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "Unknown"
        let identity = NSTextField(labelWithString: "Version \(version) · build \(build) · Private local workspace")
        identity.textColor = .secondaryLabelColor
        identityLabel = identity
        status.font = .systemFont(ofSize: 18, weight: .medium)
        detail.font = .systemFont(ofSize: 13)
        spinner.style = .spinning
        spinner.controlSize = .small
        retry = NSButton(title: "Retry", target: self, action: #selector(start))
        openUI = NSButton(title: "Open TWOS", target: self, action: #selector(openBrowser))
        prerequisite = NSButton(title: "Install Apple Command Line Tools…", target: self, action: #selector(fixPrerequisite))
        prerequisite.isHidden = true
        let logs = NSButton(title: "Open Diagnostics", target: self, action: #selector(openLogs))
        let codex = NSButton(title: "Set up Codex…", target: self, action: #selector(setupCodex))
        let quit = NSButton(title: "Quit", target: NSApp, action: #selector(NSApplication.terminate(_:)))
        recoveryButton = NSButton(title: "Recover local account…", target: self, action: #selector(recoverLocalAccount))
        languagePicker.addItems(withTitles: ["English", "简体中文"])
        languagePicker.selectItem(at: locale == "zh-CN" ? 1 : 0)
        languagePicker.target = self; languagePicker.action = #selector(changeLanguage)
        environmentPicker.target = self; environmentPicker.action = #selector(selectEnvironment)
        refreshEnvironments()
        let createEnvironment = NSButton(title: "New independent local environment", target: self, action: #selector(newEnvironment))
        let environmentRow = NSStackView(views: [environmentPicker, createEnvironment])
        environmentRow.orientation = .horizontal
        let buttons = NSStackView(views: [openUI, retry, logs, quit])
        buttons.orientation = .horizontal
        let footer = NSTextField(wrappingLabelWithString: "Closing this window quits the local service. Save your work and finish active deliveries before quitting. Your saved projects remain on this Mac.")
        footer.textColor = .secondaryLabelColor
        let stack = NSStackView(views: [title, languagePicker, identity, environmentRow, spinner, status, detail, prerequisite, buttons, codex, recoveryButton, footer])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 15
        stack.translatesAutoresizingMaskIntoConstraints = false
        window.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: window.contentView!.leadingAnchor, constant: 28),
                                     stack.trailingAnchor.constraint(equalTo: window.contentView!.trailingAnchor, constant: -28),
                                     stack.topAnchor.constraint(equalTo: window.contentView!.topAnchor, constant: 25)])
        window.center()
        if args.contains("--diagnostic-root") || args.contains("--choose-environment") { window.makeKeyAndOrderFront(nil) }
        NSApp.activate(ignoringOtherApps: true)
        openUI.isEnabled = false
        retry.title = "Open selected environment"
        status.stringValue = "Choose your local environment"
        detail.stringValue = "Continue your existing account and history, or create a separate local environment. Existing data is never reset."
        translateViews()
        languageTimer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { _ in
            self.readLanguage(); self.translateViews()
        }
        // Existing diagnostic automation retains its historical explicit mode.
        // Normal installed users choose an environment using visible controls.
        if args.contains("--diagnostic-root") && !args.contains("--choose-environment") && !args.contains("--native-workbench") { start() }
        else if !args.contains("--no-browser") && !args.contains("--choose-environment") { openNativeWorkbench() }
    }

    func readLanguage() {
        if let data = try? Data(contentsOf: preferencesURL.appendingPathComponent("ui-preference.json")),
           let value = try? JSONSerialization.jsonObject(with: data) as? [String:String],
           ["en-US", "zh-CN"].contains(value["locale"] ?? "") { locale = value["locale"]! }
    }
    func localized(_ text: String) -> String {
        let key = translations[text] != nil ? text : translations.first(where: { $0.value["zh-CN"] == text })?.key
        return key.flatMap { translations[$0]?[locale] } ?? text
    }
    func translateViews() {
        func walk(_ view: NSView) {
            if let field = view as? NSTextField { field.stringValue = localized(field.stringValue) }
            if let button = view as? NSButton, !(button is NSPopUpButton) { button.title = localized(button.title) }
            for child in view.subviews { walk(child) }
        }
        if let content = window?.contentView { walk(content) }
        languagePicker.selectItem(at: locale == "zh-CN" ? 1 : 0)
        let version=Bundle.main.object(forInfoDictionaryKey:"CFBundleShortVersionString") as? String ?? "?"
        let build=Bundle.main.object(forInfoDictionaryKey:"CFBundleVersion") as? String ?? "?"
        identityLabel?.stringValue = locale == "zh-CN" ? "版本 \(version) · 构建 \(build) · 私有本机环境" : "Version \(version) · build \(build) · Private local workspace"
        func translateMenu(_ menu: NSMenu) {
            menu.title = localized(menu.title)
            for item in menu.items {
                item.title = localized(item.title)
                if let submenu = item.submenu { translateMenu(submenu) }
            }
        }
        if let menu = NSApp.mainMenu { translateMenu(menu) }
        if !errorCode.isEmpty { renderErrorDetail() }
    }
    func renderErrorDetail() {
        let parts=detail.stringValue.components(separatedBy:"\n")
        detail.stringValue=localized(parts[0])+(locale == "zh-CN" ? "\n错误: " : "\nError: ")+errorCode+(locale == "zh-CN" ? " · 阶段: " : " · Stage: ")+startupStage
    }
    func safePreferencesDirectory() throws {
        var path = preferencesURL!
        while path.path != "/" {
            if let attrs = try? nativePathMetadata(path.path), attrs.st_mode & S_IFMT == S_IFLNK {
                throw NSError(domain:"TWOS",code:1)
            }
            path.deleteLastPathComponent()
        }
        try FileManager.default.createDirectory(at:preferencesURL,withIntermediateDirectories:true,attributes:[.posixPermissions:0o700])
    }
    @objc func changeLanguage() {
        let selected = languagePicker.indexOfSelectedItem == 1 ? "zh-CN" : "en-US"
        do {
            try safePreferencesDirectory()
            let data = try JSONSerialization.data(withJSONObject:["locale":selected])
            try data.write(to:preferencesURL.appendingPathComponent("ui-preference.json"),options:.atomic)
            locale=selected; translateViews(); refreshEnvironments()
        } catch { detail.stringValue=localized("Language preference could not be saved. Existing data is unchanged.") }
    }
    func loadEnvironments() {
        guard let data = try? Data(contentsOf:preferencesURL.appendingPathComponent("environments.json")),
              let saved = try? JSONSerialization.jsonObject(with:data) as? [String:Any] else { return }
        let rows = saved["environments"] as? [[String:String]] ?? []
        environments = rows.filter { $0["id"]?.range(of:"^env_[a-f0-9]{32}$",options:.regularExpression) != nil && ($0["name"]?.count ?? 0) <= 80 }
        let selected=saved["selected"] as? String
        if environments.contains(where: { $0["id"] == selected }) { selectedEnvironment=selected }
    }
    func saveEnvironments() throws {
        try safePreferencesDirectory()
        let value:[String:Any]=["environments":environments,"selected":selectedEnvironment ?? "original"]
        try JSONSerialization.data(withJSONObject:value).write(to:preferencesURL.appendingPathComponent("environments.json"),options:.atomic)
    }
    func refreshEnvironments() {
        environmentPicker.removeAllItems()
        environmentPicker.addItem(withTitle:localized("Original local environment"))
        for item in environments { environmentPicker.addItem(withTitle:item["name"] ?? item["id"]!) }
        environmentPicker.selectItem(at:selectedEnvironment.flatMap { id in environments.firstIndex(where: { $0["id"]==id }).map { $0+1 } } ?? 0)
    }
    @objc func selectEnvironment() {
        guard !recoveryActive else { return }
        guard service?.isRunning != true, !starting else { refreshEnvironments(); return }
        selectedEnvironment=environmentPicker.indexOfSelectedItem == 0 ? nil : environments[environmentPicker.indexOfSelectedItem-1]["id"]
        do { try saveEnvironments() } catch { fail("DESKTOP_STORAGE_UNAVAILABLE") }
    }
    @objc func newEnvironment() {
        guard !recoveryActive else { return }
        guard service?.isRunning != true, !starting else {
            detail.stringValue=localized("Quit and reopen the app before changing environments. Saved work is retained."); return
        }
        let alert=NSAlert(); alert.messageText=localized("New independent local environment")
        alert.informativeText=localized("Choose a name. A new account, projects and storage will be separate from your existing environment. No old data is copied or deleted.")
        let input=NSTextField(frame:NSRect(x:0,y:0,width:350,height:26));alert.accessoryView=input
        alert.addButton(withTitle:localized("Create environment"));alert.addButton(withTitle:localized("Cancel"))
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        let name=input.stringValue.trimmingCharacters(in:.whitespacesAndNewlines)
        guard !name.isEmpty, name.count<=80 else { detail.stringValue=localized("Enter an environment name between 1 and 80 characters, then try again."); return }
        let id="env_"+UUID().uuidString.replacingOccurrences(of:"-",with:"").lowercased()
        environments.append(["id":id,"name":name]);selectedEnvironment=id
        do { try saveEnvironments(); refreshEnvironments() } catch { environments.removeLast(); selectedEnvironment=nil; fail("DESKTOP_STORAGE_UNAVAILABLE") }
    }

    func command(_ path: String, _ arguments: [String]) -> (Int32, String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: path)
        process.arguments = arguments
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        process.standardInput = FileHandle.nullDevice
        do {
            try process.run()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            return (process.terminationStatus, String(data: data, encoding: .utf8) ?? "")
        } catch { return (-1, "") }
    }

    @objc func start() {
        guard !starting, !recoveryActive, service?.isRunning != true else { return }
        starting = true
        environmentPicker.isEnabled = false
        retry.title = localized("Retry")
        if let id=selectedEnvironment {
            let base=diagnosticRoot.map { URL(fileURLWithPath:$0).appendingPathComponent("environments") }
                ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/Tianma Work OS Environments")
            logURL=base.appendingPathComponent(id).appendingPathComponent("logs")
        }
        launchID = UUID().uuidString
        startupStage = "native_launcher"
        workspaceReview = false
        diagnosticFields = [:]
        expectedStop = false
        errorCode = ""
        readyURL = nil
        buffer = Data()
        retry.isEnabled = false
        openUI.isEnabled = false
        prerequisite.isHidden = true
        spinner.startAnimation(nil)
        status.stringValue = "Checking your Mac…"
        detail.stringValue = "No developer tools or packages need to be configured manually."
        let installedPath = Bundle.main.bundleURL.resolvingSymlinksInPath().path
        let userApplications = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications").path + "/"
        if diagnosticRoot == nil && !installedPath.hasPrefix("/Applications/") && !installedPath.hasPrefix(userApplications) {
            fail("DESKTOP_INSTALLATION_LOCATION"); return
        }
        DispatchQueue.global().async {
            let selected = self.command("/usr/bin/xcode-select", ["-p"])
            let git = selected.0 == 0 ? self.command("/usr/bin/git", ["--version"]) : (-1, "")
            DispatchQueue.main.async {
                if selected.0 != 0 { self.fail("DESKTOP_GIT_MISSING"); return }
                if git.0 != 0 { self.fail(git.1.lowercased().contains("license") ? "DESKTOP_GIT_LICENSE" : "DESKTOP_GIT_UNAVAILABLE"); return }
                self.launchService()
            }
        }
    }

    func launchService() {
        guard let resources = Bundle.main.resourceURL else { fail("DESKTOP_RUNTIME_MISSING"); return }
        let executable = resources.appendingPathComponent("engine/twos-service")
        guard FileManager.default.isExecutableFile(atPath: executable.path) else { fail("DESKTOP_RUNTIME_MISSING"); return }
        // Reject writable-by-other-users code before invoking it. Bundled symlinks
        // are validated by the packaging manifest and macOS signature verification.
        var cursor = executable
        while cursor.path != "/" {
            guard let attributes = try? nativePathMetadata(cursor.path) else { fail("DESKTOP_EXECUTABLE_UNSAFE"); return }
            let permissions = attributes.st_mode
            if permissions & 0o022 != 0 {
                let appleApplications = cursor.path == "/Applications"
                    && attributes.st_uid == 0 && attributes.st_gid == 80
                    && permissions & 0o002 == 0
                let stickyTemporary = ["/private/tmp", "/tmp"].contains(cursor.path)
                    && attributes.st_uid == 0 && permissions & 0o1000 != 0
                if !appleApplications && !stickyTemporary { fail("DESKTOP_EXECUTABLE_UNSAFE"); return }
            }
            cursor.deleteLastPathComponent()
        }
        let process = Process()
        process.executableURL = executable
        process.arguments = diagnosticRoot.map { ["--diagnostic-root", $0] } ?? []
        if let id=selectedEnvironment { process.arguments! += ["--environment-id",id] }
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        process.environment = ["HOME": home, "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "en_US.UTF-8",
                               "TMPDIR": NSTemporaryDirectory(), "USER": NSUserName(), "LOGNAME": NSUserName()]
        process.currentDirectoryURL = resources
        input = Pipe()
        output = Pipe()
        process.standardInput = input
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice // Exceptions may contain private paths or payloads.
        output!.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async { self.receive(data) }
        }
        process.terminationHandler = { child in
            DispatchQueue.main.async {
                guard self.service === child else { return }
                self.diagnosticFields = ["exit_status": child.terminationStatus,
                    "termination_reason": child.terminationReason == .exit ? "exit" : "signal"]
                self.writeDiagnostic("DESKTOP_CHILD_EXIT")
                self.starting = false
                self.retry.isEnabled = true
                self.spinner.stopAnimation(nil)
                if !self.expectedStop && self.errorCode.isEmpty { self.fail("DESKTOP_RUNTIME_EXITED") }
            }
        }
        service = process
        errorCode = ""
        status.stringValue = "Preparing Tianma Work OS…"
        detail.stringValue = "Starting the bundled runtime and initializing your private workspace."
        do {
            try process.run()
            startupStage = "child_created"
            diagnosticFields = ["child_pid": process.processIdentifier]
            writeDiagnostic("DESKTOP_CHILD_CREATED")
        } catch {
            diagnosticFields = ["process_launch_error": (error as NSError).code]
            fail("DESKTOP_RUNTIME_FAILED")
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 120) {
            if self.service === process && self.starting && self.readyURL == nil {
                self.fail("DESKTOP_STARTUP_TIMEOUT")
                self.stopOwnedService()
            }
        }
    }

    func receive(_ data: Data) {
        buffer.append(data)
        if buffer.count > 65536 { buffer.removeAll(); fail("DESKTOP_PROTOCOL_INVALID"); stopOwnedService(); return }
        while let newline = buffer.firstIndex(of: 10) {
            let line = Data(buffer[..<newline])
            buffer.removeSubrange(...newline)
            guard let value = try? JSONSerialization.jsonObject(with: line) as? [String: Any], let kind = value["event"] as? String else { continue }
            if kind == "phase", let stage = value["stage"] as? String,
               ["module_import", "application_initialization", "workspace_owner_review", "server_listen"].contains(stage) {
                startupStage = stage
                workspaceReview = workspaceReview || stage == "workspace_owner_review"
                diagnosticFields = [:]
                writeDiagnostic("DESKTOP_PHASE")
            }
            if kind == "diagnostic" {
                diagnosticFields = [:]
                for key in ["exception_type", "product_code"] {
                    if let symbol = value[key] as? String, symbol.count < 100,
                       symbol.range(of: "^[A-Za-z_][A-Za-z_0-9]*$", options: .regularExpression) != nil {
                        diagnosticFields[key] = symbol
                    }
                }
                writeDiagnostic("DESKTOP_PRODUCT_DIAGNOSTIC")
            }
            if kind == "progress" { status.stringValue = "Initializing your local workspace…" }
            if kind == "error" { fail(value["code"] as? String ?? "DESKTOP_RUNTIME_FAILED") }
            if kind == "ready", let raw = value["url"] as? String, var url = URLComponents(string: raw),
               url.scheme == "http", url.host == "127.0.0.1", ["/twos", "/projects"].contains(url.path),
               value["version"] as? String == Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String {
                if let token = value["setup"] as? String, !token.isEmpty { url.fragment = "setup=" + token }
                readyURL = url.url
                starting = false
                spinner.stopAnimation(nil)
                openUI.isEnabled = true
                status.stringValue = workspaceReview ? "Workspace review required" : "Ready"
                detail.stringValue = workspaceReview
                    ? "Your saved account and history are available. Open TWOS, log in, and review the current workspace identity. No delivery will run during recovery."
                    : "Open your workspace in the browser. Existing accounts and saved history are kept; new installations follow First Run."
                writeDiagnostic("DESKTOP_READY")
                if !CommandLine.arguments.contains("--no-browser") { openBrowser() }
            }
        }
    }

    func fail(_ code: String) {
        errorCode = code
        starting = false
        spinner.stopAnimation(nil)
        retry.isEnabled = service?.isRunning != true
        environmentPicker.isEnabled = service?.isRunning != true
        openUI.isEnabled = false
        status.stringValue = "Tianma Work OS needs attention"
        let messages = [
            "DESKTOP_INSTALLATION_LOCATION": "Drag Tianma Work OS from the installer to Applications first. Then open the installed app from Applications. No workspace has been created by this launch.",
            "DESKTOP_GIT_MISSING": "Apple's free Command Line Tools provide Git for your project history. Click Install, complete Apple's installer, then Retry.",
            "DESKTOP_GIT_LICENSE": "Open Xcode and review Apple's license and first-launch setup. Return here and Retry after completing it.",
            "DESKTOP_GIT_UNAVAILABLE": "Git is unavailable. Open Xcode to finish its setup, then Retry.",
            "DESKTOP_PORT_OCCUPIED": "Another application is using this workspace's local connection. Quit the other TWOS instance if open, then Retry. Your data was preserved.",
            "DESKTOP_NETWORK_DENIED": "macOS or your organization's security policy denied the local connection. Review the app's system permission prompt or contact your administrator, then Retry.",
            "DESKTOP_STORAGE_UNAVAILABLE": "TWOS cannot use its private storage. Check available disk space and your macOS account's folder permissions. An existing instance may already be running. Your data was preserved.",
            "DESKTOP_INSTALLATION_MISMATCH": "This saved installation belongs to a different version or location. Your data was preserved. Contact support with Diagnostics before changing it.",
            "DESKTOP_EXECUTABLE_UNSAFE": "The app or a containing folder allows other users to change its executable files. Install a fresh official copy in Applications.",
            "DESKTOP_RUNTIME_MISSING": "The bundled runtime is missing. Download a fresh official installer and replace the app in Applications. Saved data is kept separately.",
            "DESKTOP_STARTUP_TIMEOUT": "Startup did not finish. Open Diagnostics, then Retry. Reinstall the official app if this repeats."
        ]
        detail.stringValue = localized(messages[code] ?? "The local service stopped before it was ready. Open Diagnostics to review the recorded startup stage and error code. Do not delete your data or repeatedly reinstall.") + (locale == "zh-CN" ? "\n错误: " : "\nError: ") + code + (locale == "zh-CN" ? " · 阶段: " : " · Stage: ") + startupStage
        prerequisite.isHidden = !["DESKTOP_GIT_MISSING", "DESKTOP_GIT_LICENSE", "DESKTOP_GIT_UNAVAILABLE", "DESKTOP_INSTALLATION_LOCATION"].contains(code)
        prerequisite.title = code == "DESKTOP_INSTALLATION_LOCATION" ? "Open Applications" : code == "DESKTOP_GIT_MISSING" ? "Install Apple Command Line Tools…" : "Open Xcode…"
        writeDiagnostic(code)
    }

    func writeDiagnostic(_ code: String) {
        // Only fixed product codes. Never write IPC payloads, browser fragments,
        // provider output, environment variables or exception details.
        guard code.range(of: "^DESKTOP_[A-Z_]+$", options: .regularExpression) != nil else { return }
        var cursor = logURL!
        while cursor.path != "/" {
            if let attributes = try? nativePathMetadata(cursor.path),
               attributes.st_mode & S_IFMT == S_IFLNK { return }
            cursor.deleteLastPathComponent()
        }
        try? FileManager.default.createDirectory(at: logURL, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let file = logURL.appendingPathComponent("desktop-status.txt")
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "Unknown"
        let source = Bundle.main.object(forInfoDictionaryKey: "TWOSSourceCommit") as? String ?? "Unknown"
        let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "Unknown"
        try? ("Tianma Work OS \(version) / \(build)\nSource: \(source)\n\(Date())\n\(code)\nStage: \(startupStage)\n").write(to: file, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
        var record = diagnosticFields
        record.merge(["at": ISO8601DateFormatter().string(from: Date()), "code": code,
                      "stage": startupStage, "build": build, "source": source,
                      "launcher_pid": ProcessInfo.processInfo.processIdentifier]) { _, new in new }
        let events = logURL.appendingPathComponent("startup-\(launchID).jsonl")
        if let payload = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]) {
            if !FileManager.default.fileExists(atPath: events.path) {
                FileManager.default.createFile(atPath: events.path, contents: nil, attributes: [.posixPermissions: 0o600])
            }
            if let attributes = try? nativePathMetadata(events.path),
               attributes.st_mode & S_IFMT == S_IFREG, attributes.st_size < 65536,
               let handle = try? FileHandle(forWritingTo: events) {
                defer { try? handle.close() }
                _ = try? handle.seekToEnd()
                try? handle.write(contentsOf: payload + Data([10]))
            }
        }
    }

    @objc func openNativeWorkbench() {
        if nativeWorkbench == nil {
            nativeWorkbench = IntegratedWorkbench(preferences: preferencesURL, translate: { [weak self] in self?.localized($0) ?? $0 },
                                               openProjects: { [weak self] in self?.showLegacyLauncher() })
        }
        nativeWorkbench?.languageChanged = { [weak self] selected in
            guard let self = self, ["zh-CN", "en-US"].contains(selected) else { return false }
            do {
                try self.safePreferencesDirectory()
                try NativeWorkbench.save(["locale": selected], at: self.preferencesURL.appendingPathComponent("ui-preference.json"))
                self.locale = selected; self.translateViews(); return true
            } catch { self.nativeWorkbench?.codex?.notice("Language preference could not be saved. Existing data is unchanged."); return false }
        }
        nativeWorkbench?.start()
    }
    @objc func showLegacyLauncher() {
        if let url = readyURL { NSWorkspace.shared.open(url) }
        else { window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true) }
    }
    @objc func openBrowser() { if let url = readyURL { NSWorkspace.shared.open(url) } }
    @objc func openLogs() {
        if FileManager.default.fileExists(atPath: logURL.path) { NSWorkspace.shared.open(logURL) }
        else { NSWorkspace.shared.open(FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs")) }
    }
    @objc func fixPrerequisite() {
        if errorCode == "DESKTOP_INSTALLATION_LOCATION" {
            NSWorkspace.shared.open(URL(fileURLWithPath: "/Applications")); return
        }
        if errorCode == "DESKTOP_GIT_MISSING" {
            DispatchQueue.global().async {
                let result = self.command("/usr/bin/xcode-select", ["--install"])
                DispatchQueue.main.async {
                    self.detail.stringValue = result.0 == 0 ? "Complete Apple's installation dialog, then click Retry." : "Apple could not open the installer. Open System Settings → General → Software Update, install available developer tools, then Retry."
                }
            }
        } else { NSWorkspace.shared.open(URL(fileURLWithPath: "/Applications/Xcode.app")) }
    }
    @objc func setupCodex() {
        guard !recoveryActive else { return }
        let alert = NSAlert()
        alert.messageText = localized("Connect your own Codex account")
        alert.informativeText = localized("Install the official ChatGPT desktop app first. Sign in with the installed Codex tool through its browser authentication. Codex stores its own credentials; none are copied into TWOS. Then open your Project’s AI team and select the verified executable.")
        alert.addButton(withTitle: localized("Sign in through browser"))
        alert.addButton(withTitle: localized("Open official setup guide"))
        alert.addButton(withTitle: localized("Done"))
        let choice = alert.runModal()
        if choice == .alertSecondButtonReturn { NSWorkspace.shared.open(URL(string: "https://learn.chatgpt.com/docs/app")!); return }
        guard choice == .alertFirstButtonReturn, authProcess?.isRunning != true else { return }
        let locations = ["/Applications/ChatGPT.app/Contents/Resources/codex", "/Applications/Codex.app/Contents/Resources/codex"]
        guard let path = locations.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            detail.stringValue = "Install the official ChatGPT desktop app using the setup guide, then return here to sign in."
            NSWorkspace.shared.open(URL(string: "https://learn.chatgpt.com/docs/app")!); return
        }
        // Require the installed publisher's valid signature before authentication.
        DispatchQueue.global().async {
            let verification = self.command("/usr/bin/codesign", ["--verify", "--strict", path])
            DispatchQueue.main.async {
                guard verification.0 == 0 else { self.detail.stringValue = "The installed Codex executable could not be verified. Reinstall it from the official guide."; return }
                let process = Process()
                process.executableURL = URL(fileURLWithPath: path)
                process.arguments = ["login"]
                process.environment = ["HOME": FileManager.default.homeDirectoryForCurrentUser.path, "PATH": "/usr/bin:/bin", "TMPDIR": NSTemporaryDirectory()]
                process.standardInput = FileHandle.nullDevice
                process.standardOutput = FileHandle.nullDevice
                process.standardError = FileHandle.nullDevice
                process.terminationHandler = { child in
                    DispatchQueue.main.async {
                        self.detail.stringValue = child.terminationStatus == 0
                            ? "Codex sign-in completed. Open your Project’s AI team, select this tool and explicitly start an approved task."
                            : "Codex sign-in did not complete. Retry Set up Codex or consult the official setup guide."
                    }
                }
                self.authProcess = process
                do { try process.run(); self.detail.stringValue = "Complete Codex sign-in in your browser. TWOS does not receive your password." }
                catch { self.detail.stringValue = "Codex sign-in could not start. Open the official setup guide." }
            }
        }
    }
    @objc func about() {
        let commit = Bundle.main.object(forInfoDictionaryKey: "TWOSSourceCommit") as? String ?? "Unknown"
        let identity = Bundle.main.object(forInfoDictionaryKey: "TWOSSourceIdentity") as? String ?? "Unknown"
        NSApp.orderFrontStandardAboutPanel(options: [.credits: NSAttributedString(string: locale == "zh-CN" ? "源码: \(commit)\n构建身份: \(identity)\nOwner 验收是独立关卡。" : "Source: \(commit)\nBuild identity: \(identity)\nOwner acceptance is a separate gate.")])
    }
    func stopOwnedService() {
        expectedStop = true
        if let auth = authProcess, auth.isRunning { auth.terminate() }
        try? input?.fileHandleForWriting.close()
        if let process = service, process.isRunning {
            process.terminate()
            DispatchQueue.main.asyncAfter(deadline: .now() + 12) {
                if process.isRunning { kill(process.processIdentifier, SIGKILL) }
            }
        }
    }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if nativeWorkbench?.codex?.isBusy == true {
            let alert = NSAlert(); alert.messageText = localized("Codex is still working")
            alert.informativeText = localized("Return to the workbench and finish or stop the current turn before quitting.")
            alert.addButton(withTitle: localized("Return to workbench")); alert.runModal(); return .terminateCancel
        }
        nativeWorkbench?.codex?.disconnect()
        if recoveryActive {
            let alert = NSAlert()
            alert.messageText = localized("Account recovery is open")
            alert.informativeText = localized("Finish or cancel account recovery before quitting. Do not interrupt a confirmed password change.")
            alert.addButton(withTitle: localized("Return to recovery")); alert.runModal()
            return .terminateCancel
        }
        if let auth = authProcess, auth.isRunning { auth.terminate() }
        if let child = service, child.isRunning {
            let alert = NSAlert()
            alert.messageText = localized("Quit Tianma Work OS?")
            alert.informativeText = localized("Finish active deliveries before quitting. Saved projects remain on this Mac. Detached executions may need reconciliation when you return.")
            alert.addButton(withTitle: localized("Quit"))
            alert.addButton(withTitle: localized("Keep Open"))
            if !CommandLine.arguments.contains("--diagnostic-root") && alert.runModal() != .alertFirstButtonReturn { return .terminateCancel }
            stopOwnedService()
            DispatchQueue.global().async {
                child.waitUntilExit()
                DispatchQueue.main.async { NSApp.reply(toApplicationShouldTerminate: true) }
            }
            return .terminateLater
        }
        return .terminateNow
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if nativeWorkbench != nil { openNativeWorkbench() } else { window.makeKeyAndOrderFront(nil) }; return true
    }
}

extension Launcher {
    @objc func recoverLocalAccount() {
        guard !recoveryActive else { return }
        guard !starting, service?.isRunning != true, authProcess?.isRunning != true else {
            let alert = NSAlert()
            alert.messageText = localized("Quit and reopen before account recovery")
            alert.informativeText = localized("Finish active work, quit TWOS normally, reopen it and select the same environment. Choose Recover local account before Open selected environment. No account or saved work has changed.")
            alert.addButton(withTitle: localized("Done")); alert.runModal(); return
        }
        let alert = NSAlert()
        alert.messageText = localized("Recover the selected local account")
        alert.informativeText = (environmentPicker.titleOfSelectedItem ?? "") + "\n\n" + localized("Verify your macOS identity, then review the existing TWOS account. You will personally choose a new local password. The account ID, projects and delivery history stay in place; previous login sessions are revoked. No model, trade or delivery runs. You can cancel before the final confirmation.")
        alert.addButton(withTitle: localized("Verify macOS identity"))
        alert.addButton(withTitle: localized("Cancel"))
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        recoveryActive = true; recoveryCompleted = false; recoveryReported = false
        recoveryButton.isEnabled = false; environmentPicker.isEnabled = false; retry.isEnabled = false
        let context = LAContext(); recoveryAuth = context
        context.localizedCancelTitle = localized("Cancel")
        var reason: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &reason) else {
            finishRecoveryMessage("macOS identity verification is unavailable. Nothing was changed. Use your normal macOS account and try recovery again.")
            return
        }
        context.evaluatePolicy(.deviceOwnerAuthentication, localizedReason: localized("Authorize recovery of your selected local TWOS account. Your Mac password is handled by macOS, not TWOS.")) { accepted, _ in
            DispatchQueue.main.async {
                self.recoveryAuth = nil
                guard accepted else { self.finishRecoveryMessage("macOS verification was cancelled or failed. Nothing was changed."); return }
                self.launchRecovery()
            }
        }
    }

    func finishRecoveryMessage(_ message: String) {
        recoveryPrompt.dismiss()
        recoveryTimer?.cancel(); recoveryTimer = nil
        recoveryAuth?.invalidate(); recoveryAuth = nil
        try? recoveryInput?.fileHandleForWriting.close()
        // A live worker still owns the installation lease. Its exit callback
        // enables the controls; never let a second action race its transaction.
        if recoveryProcess?.isRunning != true {
            recoveryActive = false; recoveryButton.isEnabled = true
            environmentPicker.isEnabled = true; retry.isEnabled = true
        }
        recoveryReported = true
        status.stringValue = localized(recoveryCompleted ? "Account password recovered" : "Account recovery needs attention")
        detail.stringValue = localized(message)
    }

    func launchRecovery() {
        guard let resources = Bundle.main.resourceURL else { finishRecoveryMessage("The recovery runtime could not start. No password was changed."); return }
        let executable = resources.appendingPathComponent("engine/twos-service")
        // Use only the verified bundle, never a downloaded helper or source venv.
        guard FileManager.default.isExecutableFile(atPath: executable.path),
              command("/usr/bin/codesign", ["--verify", "--deep", "--strict", Bundle.main.bundlePath]).0 == 0 else {
            finishRecoveryMessage("The app signature could not be verified. No password was changed."); return
        }
        let process = Process(); process.executableURL = executable
        process.arguments = ["--twos-owner-recovery"] + (diagnosticRoot.map { ["--diagnostic-root", $0] } ?? [])
        if let id = selectedEnvironment { process.arguments! += ["--environment-id", id] }
        process.environment = ["HOME": FileManager.default.homeDirectoryForCurrentUser.path,
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TMPDIR": NSTemporaryDirectory(), "LANG": "en_US.UTF-8"]
        process.currentDirectoryURL = resources
        let incoming = Pipe(), outgoing = Pipe(); recoveryInput = incoming; recoveryOutput = outgoing
        recoveryBuffer = Data(); recoveryExited = false; recoveryEOF = false
        process.standardInput = incoming; process.standardOutput = outgoing
        process.standardError = FileHandle.nullDevice
        outgoing.fileHandleForReading.readabilityHandler = { handle in
            let bytes = handle.availableData
            if bytes.isEmpty { handle.readabilityHandler = nil }
            DispatchQueue.main.async {
                guard self.recoveryProcess === process else { return }
                if bytes.isEmpty { self.recoveryEOF = true; self.settleRecoveryExit() }
                else { self.receiveRecovery(bytes) }
            }
        }
        process.terminationHandler = { child in
            DispatchQueue.main.async {
                guard self.recoveryProcess === child else { return }
                self.recoveryExited = true
                self.settleRecoveryExit()
            }
        }
        recoveryProcess = process
        do { try process.run() }
        catch { finishRecoveryMessage("The recovery runtime could not start. No password was changed."); return }
        status.stringValue = localized("Checking the selected account…")
        // Parent closes the pipe on timeout; worker also bounds partial input.
        let timeout = DispatchWorkItem { [weak self] in
            self?.finishRecoveryMessage("Recovery timed out. If you did not confirm a password change, nothing was changed. Open Diagnostics before retrying an uncertain result.")
        }
        recoveryTimer = timeout; DispatchQueue.main.asyncAfter(deadline: .now() + 330, execute: timeout)
    }

    func settleRecoveryExit() {
        // EOF and exit may be delivered in either order. Drain all protocol
        // events before deciding that a final receipt is missing.
        guard recoveryExited && recoveryEOF else { return }
        recoveryActive = false; recoveryButton.isEnabled = true
        environmentPicker.isEnabled = true; retry.isEnabled = true
        recoveryTimer?.cancel(); recoveryTimer = nil
        recoveryPrompt.dismiss()
        if !recoveryReported {
            finishRecoveryMessage("Recovery ended without a confirmed result. Do not repeat it blindly; open Diagnostics and report this state. Saved work was not replayed.")
        }
    }

    func receiveRecovery(_ bytes: Data) {
        recoveryBuffer.append(bytes)
        if recoveryBuffer.count > 16384 { finishRecoveryMessage("Recovery returned an invalid response. Do not retry blindly; open Diagnostics."); return }
        while let newline = recoveryBuffer.firstIndex(of: 10) {
            let line = Data(recoveryBuffer[..<newline]); recoveryBuffer.removeSubrange(...newline)
            guard let value = try? JSONSerialization.jsonObject(with: line) as? [String: Any], let kind = value["event"] as? String else {
                finishRecoveryMessage("Recovery returned an invalid response. Do not retry blindly; open Diagnostics."); return
            }
            if kind == "recovery_preview" && !recoveryReported { showRecoveryForm(value) }
            else if kind == "recovery_complete" {
                recoveryCompleted = true
                finishRecoveryMessage("The existing account password was changed and old login sessions were revoked. Open selected environment, then sign in with your new password. Your original projects and history remain; do not repeat previous deliveries.")
            } else if kind == "recovery_error" {
                let code = value["code"] as? String ?? "RECOVERY_FAILED"
                let message: String
                switch code {
                case "RECOVERY_PASSWORD_INVALID": message = "Use matching passwords with 8–200 characters. Nothing was changed; start recovery again to re-enter them."
                case "RECOVERY_ALREADY_USED": message = "This installation already has a completed recovery receipt. No second reset was performed. Sign in with the recovered password or contact support."
                case "INSTALLATION_BUSY", "ACTIVE_OPERATION", "RESULT_SETTLING", "UNRESOLVED_STAGE": message = "This environment has an active connection or unresolved operation. Finish or resolve that work before recovery. No password was changed."
                case "RECOVERY_CANCELLED", "RECOVERY_TIMEOUT": message = "Recovery was cancelled or timed out before confirmation. No password was changed."
                default: message = "The account could not be safely recovered. Do not delete data or register another account. Open Diagnostics and report the error code."
                }
                finishRecoveryMessage(message)
                if code.range(of: "^[A-Z_]+$", options: .regularExpression) != nil {
                    detail.stringValue += "\n" + code
                    // Fixed code only: never save IPC, password, nonce or username.
                    diagnosticFields = ["recovery_code": code]; writeDiagnostic("DESKTOP_ACCOUNT_RECOVERY_FAILED")
                }
            }
        }
    }

    func showRecoveryForm(_ preview: [String: Any]) {
        guard let name = preview["username"] as? String, let ownerID = preview["owner_id"] as? Int,
              let installation = preview["installation_id"] as? String, let nonce = preview["nonce"] as? String,
              name.count <= 80, nonce.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else {
            finishRecoveryMessage("Recovery returned an invalid response. Do not retry blindly; open Diagnostics."); return
        }
        recoveryPrompt.show(on: window, title: localized("Set a new password for the existing account"),
            detail: localized("Existing account") + ": " + name + " · ID " + String(ownerID) + "\n" + installation + "\n\n" + localized("Only this account password changes. Projects, tasks, approvals and delivery receipts are preserved. Enter the new password twice; it is not sent to a model or stored in diagnostics."),
            action: localized("Review password change"), cancel: localized("Cancel"),
            passwordLabels: [localized("New local password (8–200 characters)"), localized("Confirm new local password")]) { choice, values in
            guard self.recoveryActive, !self.recoveryReported, self.recoveryProcess?.isRunning == true else { return }
            guard choice == .alertFirstButtonReturn else { self.finishRecoveryMessage("Recovery was cancelled. No password was changed."); return }
            guard values.count == 2, (8...200).contains(values[0].unicodeScalars.count), values[0] == values[1] else {
                self.finishRecoveryMessage("Use matching passwords with 8–200 characters. Nothing was changed; start recovery again to re-enter them."); return
            }
            self.recoveryPrompt.show(on: self.window, title: self.localized("Confirm this account password change"),
                detail: name + " · ID " + String(ownerID) + "\n" + installation + "\n\n" + self.localized("A private consistent backup is saved first. This changes the selected account password and revokes existing sessions. The account ID and saved business work remain. You must log in again. This is not product acceptance."),
                action: self.localized("Reset this account password"), cancel: self.localized("Cancel")) { confirmation, _ in
                guard self.recoveryActive, !self.recoveryReported, self.recoveryProcess?.isRunning == true else { return }
                guard confirmation == .alertFirstButtonReturn else { self.finishRecoveryMessage("Recovery was cancelled. No password was changed."); return }
                let request: [String: Any] = ["nonce": nonce, "installation_id": installation, "owner_id": ownerID,
                    "confirmation": "RESET_EXISTING_OWNER_PASSWORD", "password": values[0], "password_confirmation": values[1]]
                do {
                    guard let input = self.recoveryInput else { throw NSError(domain: "Recovery", code: 1) }
                    let payload = try JSONSerialization.data(withJSONObject: request) + Data([10])
                    try input.fileHandleForWriting.write(contentsOf: payload)
                    try input.fileHandleForWriting.close()
                    self.status.stringValue = self.localized("Saving account recovery…")
                } catch { self.finishRecoveryMessage("Recovery ended without a confirmed result. Do not repeat it blindly; open Diagnostics and report this state. Saved work was not replayed.") }
            }
        }
    }
}

let app = NSApplication.shared
let delegate = Launcher()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
