import AppKit
import WebKit

// A single app/window owns both panes. No foreign window positioning, capture,
// screen mirror, remote-control service, or keyboard synthesis is involved.
final class IntegratedWorkbench: NSWindowController {
    let preferences: URL
    let resources: URL?
    let translate: (String) -> String
    let openProjects: () -> Void
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

    init(preferences: URL, resources: URL? = nil, translate: @escaping (String) -> String, openProjects: @escaping () -> Void) {
        self.resources = resources ?? Bundle.main.resourceURL?.appendingPathComponent("engine/_internal/static_cockpit")
        self.preferences = preferences; self.translate = translate; self.openProjects = openProjects
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
        title.textColor = .secondaryLabelColor
        let spacer = NSView(); spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        let bar = NSStackView(views: [leftPicker, title, spacer, rightPicker]); bar.spacing = 18
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
        rebuild(0); rebuild(1); win.center()
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    static func validWebsite(_ raw: String) -> URL? {
        guard let url = URL(string: raw), let host = url.host, !host.isEmpty, url.user == nil, url.password == nil,
              url.query == nil, url.fragment == nil else { return nil }
        if url.scheme == "https" { return url }
        if url.scheme == "http" && ["localhost", "127.0.0.1", "[::1]"].contains(host) { return url }
        return nil
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
        kinds[index] = next
        rebuild(0); rebuild(1); save()
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
                codex?.returnResult = { [weak self] text, source in self?.bringBack(text, source: source) }
            }
            view = codex?.web ?? NSTextField(labelWithString: translate("The bundled Codex pane is unavailable."))
        } else {
            let home = Self.validWebsite(urls[index]) ?? NativeWorkbench.home
            if webPanes[index]?.serviceHome != home {
                let cacheKey = "\(index):\(home.absoluteString)"
                let pane = webCache[cacheKey] ?? NativeWorkbench(preferences: preferences, translate: translate, openProjects: openProjects,
                                           serviceHome: home, locationKey: "paired-location-\(index)-\(home.host ?? "web").json")
                pane.handoffHandler = { [weak self] text, source in self?.handoff(text, source: source, from: index) }
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
    func handoff(_ text: String, source: URL, from index: Int) {
        let destination = 1-index
        if kinds[destination] == "Codex" { codex?.stage(text, source: source); return }
        guard let target = webPanes[destination], let url = NativeWorkbench.restorableURL(target.web.url, service: target.serviceHome) else { return }
        // Explicit transfer, composer only. The website's own Send stays separate.
        target.placeDraft(text, expectedSource: url) { _ in }
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
