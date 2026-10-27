import AppKit
import Darwin

let ink = NSColor(calibratedRed: 0.075, green: 0.062, blue: 0.105, alpha: 1)
let violet = NSColor(calibratedRed: 0.70, green: 0.57, blue: 0.91, alpha: 1)

func text(_ title: String, size: CGFloat = 12, color: NSColor = .white) -> NSTextField {
    let view = NSTextField(labelWithString: title)
    view.font = .systemFont(ofSize: size)
    view.textColor = color
    view.maximumNumberOfLines = 0
    view.lineBreakMode = .byWordWrapping
    return view
}

func button(_ title: String, _ target: AnyObject, _ action: Selector, hint: String) -> NSButton {
    let b = NSButton(title: title, target: target, action: action)
    b.bezelStyle = .rounded
    b.toolTip = hint
    b.setAccessibilityLabel(hint)
    return b
}

final class PetPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

final class ArtView: NSView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    var image: NSImage? { didSet { rebuildMask(); needsDisplay = true } }
    var characterBounds: CGRect?
    var stageUnits: CGSize?
    var frameScale: CGFloat = 1
    var zoom: CGFloat = 1
    var pan = NSPoint.zero
    var dragStartPan = NSPoint.zero
    var onInput: ((String) -> Void)?
    private var didDrag = false
    var drawingRect: CGRect {
        guard let image = image else { return .zero }
        guard let box = characterBounds else { return Geometry.fit(image: image.size, in: bounds) }
        if let units = stageUnits {
            // One world scale/support plane across standing and reclining art.
            // Never enlarge a wide pose just to fill the screen height.
            let scale = min(bounds.width/units.width,(bounds.height-60)/units.height) * zoom * frameScale
            let dx = min(max(pan.x,-bounds.width*0.25),bounds.width*0.25)
            let dy = min(max(pan.y,0),bounds.height*0.25)
            return CGRect(x:bounds.midX-box.midX*scale+dx,y:60-box.minY*scale+dy,
                          width:image.size.width*scale,height:image.size.height*scale)
        }
        let scale = min(bounds.width/box.width,bounds.height/box.height) * zoom * frameScale
        let slackX = max(0,(bounds.width-box.width*scale)/2)
        let slackY = max(0,(bounds.height-box.height*scale)/2)
        let dx = min(max(pan.x,-slackX),slackX), dy = min(max(pan.y,-slackY),slackY)
        return CGRect(x: bounds.midX-box.midX*scale+dx,y: bounds.midY-box.midY*scale+dy,
                      width: image.size.width*scale,height: image.size.height*scale)
    }
    private var alphaMask = [UInt8](repeating: 0, count: 64*96*4)
    func rebuildMask() {
        guard let cg = image?.cgImage(forProposedRect: nil, context: nil, hints: nil) else { return }
        alphaMask.withUnsafeMutableBytes { bytes in
            guard let ctx = CGContext(data: bytes.baseAddress, width: 64, height: 96, bitsPerComponent: 8,
                bytesPerRow: 64*4, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return }
            ctx.clear(CGRect(x: 0, y: 0, width: 64, height: 96))
            ctx.draw(cg, in: CGRect(x: 0, y: 0, width: 64, height: 96))
        }
    }
    func containsArt(_ point: NSPoint) -> Bool {
        guard image != nil, bounds.contains(point) else { return false }
        let rect = drawingRect
        guard rect.contains(point) else { return false }
        if !isRuntime { return true }
        let x = min(63,max(0,Int((point.x-rect.minX)/rect.width*64)))
        let y = min(95,max(0,Int((rect.maxY-point.y)/rect.height*96)))
        return alphaMask[(y*64+x)*4+3] > 16
    }
    var isRuntime = false
    var onDragEnd: (() -> Void)?
    var onZoom: ((CGFloat) -> Void)?
    var onMenu: ((NSEvent) -> Void)?
    var dragStartScreen: NSPoint?
    var dragStartOrigin: NSPoint?
    private var lastDragScreen: NSPoint?
    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        guard let image = image else { return }
        let fitted = drawingRect
        // Supplied art has a baked panel background; display it honestly on white.
        if !isRuntime { NSColor.white.setFill(); fitted.fill() }
        image.draw(in: fitted, from: .zero, operation: .sourceOver, fraction: 1,
                   respectFlipped: true, hints: [.interpolation: NSImageInterpolation.high])
    }
    override func mouseDown(with event: NSEvent) {
        guard let window = window else { return }
        dragStartScreen = window.convertPoint(toScreen: event.locationInWindow)
        dragStartOrigin = window.frame.origin; dragStartPan = pan; didDrag = false; lastDragScreen = dragStartScreen
    }
    override func mouseDragged(with event: NSEvent) {
        guard let window = window, let start = dragStartScreen, let origin = dragStartOrigin else { return }
        let point = window.convertPoint(toScreen: event.locationInWindow)
        if !didDrag {
            guard hypot(point.x-start.x,point.y-start.y) >= 4 else { return }
            didDrag = true; onInput?(point.x < start.x ? "drag_start_left" : "drag_start_right")
        }
        if let previous = lastDragScreen, abs(point.x-previous.x) >= 1 {
            onInput?(point.x < previous.x ? "drag_left" : "drag_right")
            lastDragScreen = point
        }
        if window is PetPanel { window.setFrameOrigin(NSPoint(x: origin.x+point.x-start.x, y: origin.y+point.y-start.y)) }
        else { pan = NSPoint(x: dragStartPan.x+point.x-start.x,y: dragStartPan.y+point.y-start.y); needsDisplay = true }
    }
    override func mouseUp(with event: NSEvent) {
        onInput?(didDrag ? "release" : "click")
        dragStartScreen = nil; dragStartOrigin = nil; lastDragScreen = nil; onDragEnd?()
    }
    override func rightMouseDown(with event: NSEvent) { onMenu?(event) }
    override func scrollWheel(with event: NSEvent) {
        guard abs(event.scrollingDeltaY) > 0.1 else { return }
        onZoom?(event.scrollingDeltaY > 0 ? 1.08 : 0.92)
    }
    override func magnify(with event: NSEvent) { onZoom?(1 + event.magnification) }
}

final class StageView: NSView {
    override var isOpaque: Bool { false }
    func visibleHit(_ point: NSPoint) -> Bool {
        if actions.contains(where: { !$0.isHidden && $0.frame.contains(point) }) { return true }
        if let wardrobe = wardrobe, !wardrobe.isHidden && wardrobe.frame.contains(point) { return true }
        return art.containsArt(art.convert(point,from:self))
    }
    let art = ArtView()
    let title = text("夜璃 · Nyra", size: 27)
    let subtitle = text("V3 / 黑紫成年猫耳 / STATIC_PREVIEW", size: 12, color: violet)
    let note = text("", size: 12, color: .lightGray)
    let truth = text("", size: 12, color: violet)
    let quality = text("", size: 11, color: .lightGray)
    let boundary = text("静态参考预览 · 动画素材缺失 · 原创声音未制作 · TWOS 未连接", size: 11, color: .lightGray)
    var wardrobe: NSSegmentedControl!
    var actions: [NSButton] = []
    var previewOutfit: Outfit?
    private var controlsVisible = true
    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        // Only small control backplates are opaque; the character stage is clear.
        ink.withAlphaComponent(0.92).setFill()
        if controlsVisible {
            NSBezierPath(roundedRect:NSRect(x:8,y:bounds.height-88,width:min(760,bounds.width-16),height:80),xRadius:12,yRadius:12).fill()
            NSBezierPath(roundedRect:NSRect(x:8,y:0,width:min(850,bounds.width-16),height:100),xRadius:12,yRadius:12).fill()
        }
    }
    func revealControls(_ visible: Bool) {
        if controlsVisible != visible { controlsVisible = visible; needsDisplay = true }
        for view in [title,subtitle,truth,boundary,wardrobe].compactMap({ $0 as NSView? }) + actions { view.isHidden = !visible }
    }
    override init(frame: NSRect) {
        super.init(frame: frame)
        wantsLayer = true; layer?.backgroundColor = NSColor.clear.cgColor; layer?.isOpaque = false
        for view in [art, title, subtitle, note, truth, quality, boundary] as [NSView] { addSubview(view) }
        art.onDragEnd = nil
    }
    required init?(coder: NSCoder) { fatalError() }
    override func layout() {
        super.layout()
        let w = bounds.width, h = bounds.height
        art.frame = NSRect(x: 24,y: 35,width: w-48,height: max(50,h-70))
        title.frame = NSRect(x: 20,y: h-39,width: 190,height: 28)
        title.font = .systemFont(ofSize: 17, weight: .medium)
        subtitle.frame = NSRect(x: 210,y: h-34,width: w-230,height: 20)
        wardrobe?.frame = NSRect(x: 20,y: h-76,width: min(390,w-40),height: 28)
        note.isHidden = true; quality.isHidden = true
        truth.isHidden = !controlsVisible; boundary.isHidden = !controlsVisible
        truth.frame = NSRect(x: 20,y: 63,width: w-40,height: 22)
        boundary.frame = NSRect(x: 20,y: 44,width: w-40,height: 18)
        let actionWidth = min(120,(w-40)/CGFloat(max(1,actions.count)))
        for (i,b) in actions.enumerated() { b.frame = NSRect(x: 20+CGFloat(i)*actionWidth,y: 8,width: actionWidth-5,height: 30) }
        if let outfit = previewOutfit {
            let shown = Geometry.fit(image: CGSize(width: outfit.width, height: outfit.height), in: art.bounds)
            let factor = shown.height/CGFloat(outfit.height)*(window?.backingScaleFactor ?? 1)
            quality.stringValue = String(format: "源图 %d × %d px · 当前显示约 %.1f× 源像素%@", outfit.width, outfit.height, factor,
                                         factor > 1 ? " · 放大会显像素；未提升原始清晰度" : "")
        }
    }
}

final class Companion: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var wardrobe: Wardrobe!
    var library: R4Library!
    var reactive = ReactiveState()
    var useRecline = false
    var poseArbiter = PoseArbiter()
    var lastRenderedAction = ""
    var lastRequested = ""
    var lastSetKey = ""
    var hoverEdge = HoverEdgeTracker()
    var pointerInside = false
    var pointerDirection = ""
    var sleepObserver: NSObjectProtocol?
    var wakeObserver: NSObjectProtocol?
    var live = NyraStatusClient()
    var liveReducer = StatusReducer()
    var livePollTimer: Timer?
    var suspended = false
    var standingSetKey: String { wardrobe.outfits[selected].id.replacingOccurrences(of:"runtime-",with:"") }
    var reclineSetKey: String { selected == 0 ? "recline" : "recline_" + standingSetKey }
    var activeSetKey: String { useRecline && poseArbiter.phase == .reclining ? reclineSetKey : standingSetKey }
    func availableSequence(_ name: String) -> FrameSequence? {
        if useRecline && PoseArbiter.standingActions.contains(name) { return library.sets[standingSetKey]?.sequences[name] }
        return library.sets[useRecline ? reclineSetKey : standingSetKey]?.sequences[name]
    }
    var activeSet: R4Set { library.sets[activeSetKey]! }
    func receiveInput(_ name: String) {
        reactive.input(name,now: ProcessInfo.processInfo.systemUptime)
        reconcileAnimation(); writePlaybackState(name)
    }
    func clearPointerState() {
        reactive.endPreview(); hoverEdge.reset(); poseArbiter.reset(reclining:useRecline)
        reactive.gaze = "idle"; reactive.dragging = false; reactive.transient = nil; reactive.debug = nil
        pointerInside = false; pointerDirection = ""
        panelView?.art.dragStartScreen = nil; panelView?.art.dragStartOrigin = nil
        stageView?.art.dragStartScreen = nil; stageView?.art.dragStartOrigin = nil
    }
    func reconcileAnimation(force: Bool = false) {
        guard library != nil, panel != nil else { return }
        reactive.expireVisuals(now: ProcessInfo.processInfo.systemUptime)
        let desired = reactive.selected(now: ProcessInfo.processInfo.systemUptime)
        let rendered = poseArbiter.resolve(reclining:useRecline,action:desired,now:ProcessInfo.processInfo.systemUptime)
        if force || rendered != lastRenderedAction || activeSetKey != lastSetKey {
            lastRenderedAction = rendered; lastSetKey = activeSetKey; playAnimation(rendered)
        }
        lastRequested = desired
        let missing = availableSequence(desired) == nil ? " · 此服装缺该动作，保持本装待机" : ""
        panelView.detail.stringValue = reactive.label + missing
        stageView?.truth.stringValue = reactive.label + missing
    }
    var images: [String: NSImage] = [:]
    var selected = 0
    var panel: PetPanel!
    var panelView: PanelView!
    var stage: NSWindow?
    var stageView: StageView?
    var status: NSStatusItem!
    let sound = NyraAudio()
    var soundPopover: NSPopover?
    var hoverTimer: Timer?
    var resizeStartHeight: CGFloat = 280
    let animationNames = ["idle", "working", "gaze_head", "verified_success", "running_right", "running_left", "waving", "jumping", "failed", "waiting", "review", "look_around"]
    let animationLabels = ["待机 / Idle", "工作 / Work", "抬头 / Look up", "庆祝 / Celebrate", "右跑 / Run right", "左跑 / Run left", "挥手 / Wave", "跳跃 / Jump", "失落 / Sad", "等待 / Wait", "阅读 / Read", "环顾 / Look around"]
    var desiredHeight: CGFloat = 400
    var passThrough = false
    var demo: DemoState = .none
    var screenObserver: NSObjectProtocol?
    var motionObserver: NSObjectProtocol?
    var runtimePlan: RuntimePlan?
    var frameCursor: FrameCursor?
    var frameImages: [String: NSImage] = [:]
    var frameTimer: Timer?
    var animationName = "idle"
    var displayedFrames: [String: Int] = [:]
    var framesDuringDrag: [String: Int] = [:]
    let resources = Bundle.main.resourceURL!
    var lockFD: Int32 = -1
    var launchVisibility: Bool?
    var lastPublishedVisibility: [String:Any] = [:]
    var isBundled: Bool { Bundle.main.bundleIdentifier == "com.tianma.workos.nyra" }
    var isolated: Bool { Bundle.main.bundleIdentifier == "com.tianma.nyra.joint.engineering" || CommandLine.arguments.contains("--diagnostic-root") || ProcessInfo.processInfo.environment["NYRA_ISOLATED_ENGINEERING"] == "1" }
    var stateDirectory: URL {
        if let i = CommandLine.arguments.firstIndex(of:"--diagnostic-root"), i+1 < CommandLine.arguments.count {
            let value = CommandLine.arguments[i+1]
            if value.hasPrefix("/"), !value.contains("/../") { return URL(fileURLWithPath:value,isDirectory:true).standardizedFileURL }
        }
        if isBundled, let raw = ProcessInfo.processInfo.environment["TWOS_NYRA_STATE_ROOT"], raw.hasPrefix("/"), !raw.contains("/../") {
            return URL(fileURLWithPath:raw,isDirectory:true).standardizedFileURL
        }
        if Bundle.main.bundleIdentifier == "com.tianma.nyra.joint.engineering" {
            return FileManager.default.temporaryDirectory.appendingPathComponent("Nyra-Joint-Engineering-" + String(getuid()),isDirectory:true)
        }
        return FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent(isBundled ? "Tianma Work OS/Nyra" : "Nyra",isDirectory:true)
    }
    var preferenceDirectory: URL {
        isolated ? stateDirectory : FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("Nyra",isDirectory:true)
    }
    var prefsURL: URL { preferenceDirectory.appendingPathComponent("preview-settings.json") }

    func applicationDidFinishLaunching(_ notification: Notification) {
        do {
            try FileManager.default.createDirectory(at: stateDirectory, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: preferenceDirectory, withIntermediateDirectories:true)
            let previousBundledPrefs = stateDirectory.appendingPathComponent("preview-settings.json")
            if !isolated, previousBundledPrefs != prefsURL, !FileManager.default.fileExists(atPath:prefsURL.path), FileManager.default.fileExists(atPath:previousBundledPrefs.path) {
                try FileManager.default.copyItem(at:previousBundledPrefs,to:prefsURL)
            }
            let legacySettings = Bundle.main.bundleURL.deletingLastPathComponent().appendingPathComponent(".local/preview-settings.json")
            if !FileManager.default.fileExists(atPath: prefsURL.path), FileManager.default.fileExists(atPath: legacySettings.path) {
                try FileManager.default.copyItem(at: legacySettings, to: prefsURL)
            }
            guard acquireSingleInstance() else { return }
            sound.customDirectory = preferenceDirectory
            let data = try Data(contentsOf: resources.appendingPathComponent("assets/outfits.json"))
            wardrobe = try JSONDecoder().decode(Wardrobe.self, from: data).validated()
            let runtimeData = try Data(contentsOf: resources.appendingPathComponent("runtime/standalone_r3.json"))
            runtimePlan = try JSONDecoder().decode(RuntimePlan.self, from: runtimeData).validated()
            for id in Set(runtimePlan!.sequences.values.flatMap(\.assetIDs)) {
                guard FileManager.default.fileExists(atPath: resources.appendingPathComponent("runtime/default/\(id).png").path)
                else { throw PreviewError.imageMissing(id) }
            }
            for outfit in wardrobe.outfits {
                let path = resources.appendingPathComponent("assets/"+outfit.file)
                guard let image = NSImage(contentsOf: path) else { throw PreviewError.imageMissing(outfit.file) }
                image.size = NSSize(width: outfit.width, height: outfit.height)
                images[outfit.id] = image
            }
            library = try JSONDecoder().decode(R4Library.self,from: Data(contentsOf: resources.appendingPathComponent("runtime/r4.json"))).validated()
            guard Set(wardrobe.outfits.map(\.id)) == ["runtime-default","runtime-office","runtime-gala"] else { throw PreviewError.invalidManifest }
            for set in library.sets.values {
                for id in Set(set.sequences.values.flatMap(\.assetIDs)) {
                    guard FileManager.default.fileExists(atPath: resources.appendingPathComponent("runtime/\(set.folder)/\(id).png").path) else { throw PreviewError.imageMissing(id) }
                }
            }
            NSApp.setActivationPolicy(.accessory)
            makeMainMenu()
            status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
            status.button?.title = "◈ 夜璃"
            status.button?.toolTip = "夜璃 · Nyra｜悬停 + 控制环"
            makePanel()
            restoreSettings()
            updateOutfit()
            let savedVisibility = (try? Data(contentsOf:preferenceDirectory.appendingPathComponent("visibility-preference.json"))).flatMap { try? JSONSerialization.jsonObject(with:$0) as? [String:Bool] }?["visible"]
            if launchVisibility ?? savedVisibility ?? true { showPanel() } else { hideAll() }
            launchVisibility = nil
            screenObserver = NotificationCenter.default.addObserver(forName: NSApplication.didChangeScreenParametersNotification,
                                                                     object: nil, queue: .main) { [weak self] _ in self?.clampPanel() }
            motionObserver = NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.accessibilityDisplayOptionsDidChangeNotification,
                object: nil, queue: .main) { [weak self] _ in
                    guard let self = self else { return }
                    self.playAnimation(self.animationName)
                }
            sleepObserver = NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.willSleepNotification, object:nil, queue:.main) { [weak self] _ in
                self?.suspended = true; self?.clearPointerState(); self?.stopFrameTimer(); self?.hoverTimer?.invalidate(); self?.livePollTimer?.invalidate(); self?.sound.stop(); self?.liveReducer.disconnect()
            }
            wakeObserver = NSWorkspace.shared.notificationCenter.addObserver(forName: NSWorkspace.didWakeNotification, object:nil, queue:.main) { [weak self] _ in
                guard let self = self else { return }; self.suspended = false
                if self.panel.isVisible || self.stage?.isVisible == true { self.startHoverTimer(); self.reconcileAnimation(force:true) }
                self.startLivePolling()
            }
            startLivePolling()
            rebuildMenu()
        } catch {
            let alert = NSAlert()
            alert.messageText = "夜璃无法启动 / Nyra could not start"
            alert.informativeText = "随包资源不可用：\(error)。请重新安装完整应用。 / A bundled resource is unavailable. Reinstall the complete app."
            alert.runModal()
            NSApp.terminate(nil)
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if panel != nil && !panel.isVisible && stage?.isVisible != true { showPanel() }
        return false
    }

    func makeMainMenu() {
        let menu = NSMenu()
        let item = NSMenuItem(); let appMenu = NSMenu()
        let quit = NSMenuItem(title: "退出 / Quit", action: #selector(quit), keyEquivalent: "q")
        quit.target = self; appMenu.addItem(quit); item.submenu = appMenu
        menu.addItem(item); NSApp.mainMenu = menu
    }

    func makePanel() {
        panel = PetPanel(contentRect: NSRect(x: 100, y: 100, width: 220, height: 388),
                         styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        panel.title = "夜璃 · Nyra｜交互桌宠"
        panel.appearance = NSAppearance(named: .darkAqua)
        panel.isOpaque = false; panel.backgroundColor = .clear
        panel.hasShadow = false; panel.level = .floating
        panel.hidesOnDeactivate = false; panel.isReleasedWhenClosed = false
        panel.isMovableByWindowBackground = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.acceptsMouseMovedEvents = true
        panelView = PanelView(frame: panel.contentView!.bounds)
        panel.contentView = panelView
        panelView.art.onDragEnd = { [weak self] in self?.clampPanel(); self?.saveSettings() }
        panelView.onDragEnd = panelView.art.onDragEnd
        panelView.art.onZoom = { [weak self] f in self?.resize(factor: f) }
        panelView.art.onMenu = { [weak self] event in
            guard let self = self, let menu = self.status.menu else { return }
            NSMenu.popUpContextMenu(menu, with: event, for: self.panelView.art)
        }
        let specs: [(String, Selector, String)] = [
            ("tshirt", #selector(nextOutfit), "一键换装 · 黑紫 / 职场 / 晚礼服"),
            ("arrow.up.left.and.arrow.down.right", #selector(fullscreen), "透明舞台 / Transparent stage"),
            ("speaker.wave.2", #selector(showSound), "声音 · 试听 / 静音 / 音量"),
            ("play.fill", #selector(showAnimationMenu), "动作 / Actions"),
            ("minus", #selector(smaller), "缩小夜璃"),
            ("plus", #selector(larger), "放大夜璃"),
            ("eye.slash", #selector(hideAll), "隐藏夜璃 · 菜单栏可恢复"),
            ("power", #selector(quit), "退出 / Quit")]
        panelView.controls = specs.map { orbitButton($0.0, title: $0.2, target: self, action: $0.1) }
        for b in panelView.controls { panelView.addSubview(b) }
        panelView.art.onInput = { [weak self] name in self?.receiveInput(name) }
        panelView.configureHub()
        panelView.grip.onBegin = { [weak self] in self?.resizeStartHeight = self?.desiredHeight ?? 280 }
        panelView.grip.onResize = { [weak self] delta in
            guard let self = self else { return }
            self.desiredHeight = min(max(self.resizeStartHeight+delta,160),max(160,self.currentScreen().visibleFrame.height-64))
            self.setPanelSize()
        }
        panelView.grip.onEnd = { [weak self] in self?.saveSettings(); self?.writePlaybackState("drag_resize") }
        let screen = currentScreen().visibleFrame
        panel.setFrameOrigin(NSPoint(x: screen.maxX-panel.frame.width-24, y: screen.minY+40))
    }

    func currentScreen() -> NSScreen {
        panel.screen ?? NSScreen.main ?? NSScreen.screens[0]
    }

    func resize(factor: CGFloat) {
        guard factor.isFinite, factor > 0 else { return }
        desiredHeight = min(max(desiredHeight*factor, 160), max(160, currentScreen().visibleFrame.height-64))
        setPanelSize(); saveSettings()
    }
    func setPanelSize() {
        guard panel != nil else { return }
        let available = currentScreen().visibleFrame
        let artHeight = min(desiredHeight, max(100, available.height-64))
        let outfit = wardrobe.outfits[selected]
        let width = max(320, artHeight*CGFloat(outfit.width)/CGFloat(outfit.height)+70)
        let origin = panel.frame.origin
        panel.setFrame(Geometry.clamp(NSRect(x: origin.x, y: origin.y, width: width, height: artHeight+52), to: available), display: true)
        panelView.needsLayout = true
        updateHitTesting()
    }
    @objc func smaller() { resize(factor: 0.85) }
    @objc func larger() { resize(factor: 1.18) }
    @objc func resetPosition() {
        let screen = currentScreen().visibleFrame
        panel.setFrameOrigin(NSPoint(x: screen.maxX-panel.frame.width-24, y: screen.minY+40))
        clampPanel(); saveSettings()
    }
    func clampPanel() {
        guard panel != nil, !NSScreen.screens.isEmpty else { return }
        let screen = NSScreen.screens.max { a, b in
            let ia = a.visibleFrame.intersection(panel.frame), ib = b.visibleFrame.intersection(panel.frame)
            return ia.width*ia.height < ib.width*ib.height
        }!
        panel.setFrame(Geometry.clamp(panel.frame, to: screen.visibleFrame), display: true)
        updateHitTesting()
    }

    func updateHitTesting() {
        guard panel != nil, !suspended else { return }
        if NSEvent.pressedMouseButtons == 0 {
            panelView.layoutSubtreeIfNeeded()
            let point = panelView.convert(panel.convertPoint(fromScreen: NSEvent.mouseLocation), from: nil)
            panelView.setHovered(panelView.bounds.insetBy(dx:-8,dy:-8).contains(point))
            panel.ignoresMouseEvents = passThrough || !panelView.visibleHit(point)
            let art = stage?.isVisible == true ? stageView!.art : panelView.art
            if let window = art.window {
                let p = art.convert(window.convertPoint(fromScreen: NSEvent.mouseLocation),from:nil)
                if let view = stageView, window == stage {
                    let local = view.convert(window.convertPoint(fromScreen:NSEvent.mouseLocation),from:nil)
                    view.revealControls(true) // Keep menus and the exit action reachable; blank art still passes through.
                    window.ignoresMouseEvents = !view.visibleHit(local)
                }
                let inside = art.containsArt(p) && art.bounds.contains(p) && (!passThrough || stage?.isVisible == true)
                let artRect = art.drawingRect
                let imageScale = artRect.width / CGFloat(activeSet.width)
                let localBox = CGRect(x:artRect.minX+activeSet.rect.minX*imageScale,y:artRect.minY+activeSet.rect.minY*imageScale,
                                      width:activeSet.rect.width*imageScale,height:activeSet.rect.height*imageScale)
                let windowBox = art.convert(localBox,to:nil)
                let screenBox = window.convertToScreen(windowBox)
                if let edge = hoverEdge.observe(point:NSEvent.mouseLocation,alphaHit:inside,character:screenBox) { receiveInput(edge) }
                pointerInside = hoverEdge.inside
                if inside {
                    let rect = art.drawingRect
                    let scale = rect.width / CGFloat(activeSet.width)
                    let box = CGRect(x:rect.minX+activeSet.rect.minX*scale,y:rect.minY+activeSet.rect.minY*scale,
                                     width:activeSet.rect.width*scale,height:activeSet.rect.height*scale)
                    let direction = PointerDirection.name(point:p,character:box,sixteen:activeSetKey == "default",previous:pointerDirection)
                    if direction != pointerDirection { pointerDirection = direction; receiveInput(direction) }
                } else { pointerDirection = "" }
            }
        }
        reconcileAnimation()
    }
    func startHoverTimer() {
        hoverTimer?.invalidate()
        let t = Timer(timeInterval: 0.1, repeats: true) { [weak self] _ in self?.updateHitTesting() }
        t.tolerance = 0.03; hoverTimer = t; RunLoop.main.add(t, forMode: .common)
    }
    @objc func showPanel() {
        if let stage = stage { stage.orderOut(nil) }
        useRecline = false; clearPointerState()
        panel.orderFrontRegardless(); updateOutfit(); clampPanel(); startHoverTimer(); updateHitTesting(); reconcileAnimation(force:true); rebuildMenu(); publishVisibility()
    }
    @objc func hideAll() {
        restoreDesktopPlacement()
        hoverTimer?.invalidate(); hoverTimer = nil; sound.stop(); soundPopover?.close()
        stopFrameTimer(); clearPointerState()
        pointerInside = false; pointerDirection = ""
        panel.orderOut(nil)
        stage?.orderOut(nil)
        writePlaybackState("hidden")
        rebuildMenu(); publishVisibility()
    }
    @objc func toggleVisibility() {
        if panel.isVisible || stage?.isVisible == true { hideAll() } else { showPanel() }
    }
    @objc func togglePassThrough() {
        passThrough.toggle(); updateHitTesting(); rebuildMenu()
    }

    @objc func nextOutfit() {
        let wearable = wardrobe.outfits.indices.filter { wardrobe.outfits[$0].isTransparentArt }
        let position = wearable.firstIndex(of: selected) ?? -1
        selected = wearable[(position+1)%wearable.count]
        updateOutfit(); saveSettings(); sound.chime("outfit")
    }
    @objc func selectOutfit(_ sender: NSMenuItem) {
        selected = sender.tag; updateOutfit(); saveSettings()
    }
    @objc func selectSegment(_ sender: NSSegmentedControl) {
        selected = sender.selectedSegment; updateOutfit(); saveSettings()
    }
    func updateOutfit() {
        let outfit = wardrobe.outfits[selected]
        poseArbiter.reset(reclining:useRecline)
        stopFrameTimer(); frameImages.removeAll(); frameCursor = nil
        panelView.art.isRuntime = true; stageView?.art.isRuntime = true
        panelView.badge.stringValue = "夜璃 · " + outfit.name
        stageView?.wardrobe.selectedSegment = selected; stageView?.previewOutfit = outfit
        stageView?.subtitle.stringValue = useRecline ? outfit.name + " · 侧卧 / Reclining" : outfit.name + " / Standing"
        stageView?.boundary.stringValue = "空白区域可穿透 · Esc 返回桌面 / Click through blank space · Esc returns to desktop"
        stageView?.art.pan = .zero
        setPanelSize(); reconcileAnimation(force:true); rebuildMenu()
    }
    @objc func togglePose() {
        useRecline.toggle(); stageView?.art.zoom = 1; updateOutfit(); writePlaybackState("pose_changed")
    }

    func makeStage() {
        let w = StageWindow(contentRect: NSRect(x: 0, y: 0, width: 900, height: 800),
                         styleMask: [.borderless], backing: .buffered, defer: false)
        w.title = "夜璃 · Nyra｜全屏舞台"
        w.onEscape = { [weak self] in self?.backToDesktop() }
        w.appearance = NSAppearance(named: .darkAqua)
        w.isOpaque = false; w.backgroundColor = .clear; w.hasShadow = false; w.level = .floating
        w.acceptsMouseMovedEvents = true
        w.isReleasedWhenClosed = false; w.delegate = self
        w.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        let view = StageView(frame: w.contentView!.bounds)
        view.art.stageUnits = CGSize(width:1600,height:1536)
        view.wardrobe = NSSegmentedControl(labels: wardrobe.outfits.map(\.name), trackingMode: .selectOne,
                                          target: self, action: #selector(selectSegment))
        view.wardrobe.setAccessibilityLabel("选择真实运行服装")
        view.addSubview(view.wardrobe)
        view.art.onInput = { [weak self] name in self?.receiveInput(name) }
        view.art.onZoom = { [weak self, weak view] factor in
            guard let art = view?.art else { return }; art.zoom = min(1,max(0.5,art.zoom*factor)); art.needsDisplay = true
            self?.writePlaybackState("stage_zoom")
        }
        view.art.onMenu = { [weak self] event in guard let self = self else { return }; NSMenu.popUpContextMenu(self.makeAnimationMenu(),with:event,for:view.art) }
        view.actions = [button("姿态 / Pose", self, #selector(togglePose), hint: "三套服装均支持站姿与侧卧 / All three outfits"), button("桌面 / Desktop", self, #selector(backToDesktop), hint: "回到浮动桌宠"),
                        button("舞台 / Stage", self, #selector(fullscreen), hint: "切换全屏展示"),
                        button("动作 / Actions", self, #selector(showAnimationMenu), hint: "动作试播 / Manual preview · 不改任务状态"),
                        button("声音 / Sound", self, #selector(showSound), hint: "声音 · 试听 / 静音 / 音量"),
                        button("隐藏 / Hide", self, #selector(hideAll), hint: "隐藏全部预览"),
                        button("退出 / Quit", self, #selector(quit), hint: "完全退出独立夜璃进程")]
        view.actions.forEach { view.addSubview($0) }
        w.contentView = view
        stage = w; stageView = view
        w.center()
    }
    var desktopBeforeStage: (frame: NSRect, height: CGFloat, outfit: Int)?
    @objc func showStage() {
        if stage == nil { makeStage() }
        if stage?.isVisible != true { desktopBeforeStage = (panel.frame,desiredHeight,selected) }
        let screen = panel.screen ?? NSScreen.main ?? NSScreen.screens[0]
        stage!.setFrame(screen.frame,display:true)
        panel.orderOut(nil); soundPopover?.close(); clearPointerState()
        stage!.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps:true)
        updateOutfit(); startHoverTimer(); rebuildMenu(); publishVisibility(); writePlaybackState("stage_opened")
    }
    @objc func fullscreen() {
        if stage?.isVisible == true { backToDesktop() } else { showStage() }
    }
    func restoreDesktopPlacement() {
        if let saved = desktopBeforeStage {
            selected = saved.outfit; desiredHeight = saved.height
            panel.setFrame(saved.frame,display:true); desktopBeforeStage = nil
        }
    }
    @objc func backToDesktop() {
        stage?.orderOut(nil); restoreDesktopPlacement()
        showPanel(); saveSettings(); writePlaybackState("stage_closed")
    }
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        hideAll(); return false
    }
    @objc func showDemoMenu(_ sender: NSButton) {
        let menu = makeDemoMenu()
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: sender.bounds.maxY), in: sender)
    }
    func makeDemoMenu() -> NSMenu {
        let menu = NSMenu(title: "SIMULATION")
        for (i,state) in DemoState.allCases.enumerated() {
            let item = NSMenuItem(title: state.menuTitle, action: #selector(selectDemo), keyEquivalent: "")
            item.target = self; item.tag = i; item.state = state == demo ? .on : .off; item.isEnabled = !liveReducer.connected
            menu.addItem(item)
        }
        return menu
    }
    @objc func selectDemo(_ sender: NSMenuItem) {
        guard !liveReducer.connected else { return }
        demo = DemoState.allCases[sender.tag]
        let map: [DemoState: WorkState] = [.none:.idle,.received:.queued,.running:.running,.approval:.waiting_user,.completedUnverified:.completed_unverified,.partial:.partial,.failed:.failed,.verified:.verified_success,.accepted:.completed_unverified,.disconnected:.disconnected]
        if liveReducer.connected { demo = .none; return }
        reactive.setWork(map[demo] ?? .idle,simulation:demo != .none,connected:false,celebrate:demo == .verified,now:ProcessInfo.processInfo.systemUptime)
        reconcileAnimation(force:true); writePlaybackState("simulation_state"); rebuildMenu()
    }

    func stopFrameTimer() { frameTimer?.invalidate(); frameTimer = nil }
    var mayAnimate: Bool {
        !suspended && (panel.isVisible || stage?.isVisible == true)
            && !NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    }
    func playAnimation(_ name: String) {
        stopFrameTimer()
        let set = activeSet
        let (resolved,seq) = set.resolve(name)
        animationName = resolved; frameCursor = FrameCursor(sequence:seq); frameImages.removeAll()
        for id in Set(seq.assetIDs + [set.neutral]) {
            if let im = NSImage(contentsOf:resources.appendingPathComponent("runtime/\(set.folder)/\(id).png")) {
                im.size = NSSize(width:set.width,height:set.height); frameImages[id] = im
            }
        }
        panelView.art.characterBounds = set.rect; stageView?.art.characterBounds = set.rect
        if NSWorkspace.shared.accessibilityDisplayShouldReduceMotion {
            panelView.art.image = frameImages[set.neutral]; stageView?.art.image = frameImages[set.neutral]
            writePlaybackState("reduced_motion"); return
        }
        displayFrame(); scheduleFrame(); writePlaybackState("animation_started")
    }
    func displayFrame() {
        guard let cursor = frameCursor, let im = frameImages[cursor.assetID] else { return }
        let scale = CGFloat(activeSet.frame_scales?[cursor.assetID] ?? 1)
        panelView.art.frameScale = scale; stageView?.art.frameScale = scale
        panelView.art.image = im; stageView?.art.image = im
        displayedFrames[activeSetKey+":"+animationName,default:0] += 1
        if reactive.dragging { framesDuringDrag[activeSetKey+":"+animationName,default:0] += 1 }
        if displayedFrames[activeSetKey+":"+animationName,default:0] % 6 == 0 { writePlaybackState("frame_progress") }
    }
    func writePlaybackState(_ event: String) {
        // Local evidence about this app only. No TWOS events, screen capture or personal data.
        let state: [String: Any] = ["pid": ProcessInfo.processInfo.processIdentifier,
            "work_order":"TWOS-NYRA-1_0-JOINT-RELEASE-R1", "reactive_inputs":reactive.counts,
            "requested_animation":lastRequested,"pose":activeSetKey,"pose_transition":poseArbiter.phase.rawValue,"frame_asset":frameCursor?.assetID ?? "",
            "task_state":reactive.work.rawValue,"simulation":reactive.simulation,"twos_connection":live.connectionLabel,
            "celebration_count":liveReducer.celebrationCount,"character_bbox":activeSet.bbox,
            "stage_art_rect":stageView.map { NSStringFromRect($0.art.drawingRect) } ?? "",
            "stage_zoom":stageView?.art.zoom ?? 1,
            "event": event, "animation": animationName, "displayed_frames": displayedFrames, "frames_during_drag": framesDuringDrag,
            "panel_visible": panel.isVisible, "stage_visible": stage?.isVisible == true,
            "control_ring_expanded": panelView.expanded, "hover_timer_scheduled": hoverTimer?.isValid == true,
            "outfit": wardrobe.outfits[selected].id, "desired_height": desiredHeight,
            "window_frame": NSStringFromRect(panel.frame), "sound": sound.snapshot,
            "stage_fullscreen": stage?.isVisible == true, "stage_transparent": stage?.isOpaque == false,
            "manual_preview": reactive.debugTrial, "manual_preview_until": reactive.debugUntil,
            "timer_scheduled": frameTimer?.isValid == true,
            "reduce_motion": NSWorkspace.shared.accessibilityDisplayShouldReduceMotion,
            "uptime": ProcessInfo.processInfo.systemUptime]
        if let data = try? JSONSerialization.data(withJSONObject: state, options: [.sortedKeys]) {
            try? data.write(to: stateDirectory.appendingPathComponent("playback-state.json"), options: .atomic)
        }
    }
    func scheduleFrame() {
        guard mayAnimate, let cursor = frameCursor else { return }
        let timer = Timer(timeInterval: cursor.duration, repeats: false) { [weak self] _ in
            guard let self = self, self.mayAnimate else { return }
            self.frameCursor?.advance()
            if self.frameCursor?.finished == true {
                self.stopFrameTimer()
                if !self.poseArbiter.transitioning && (self.reactive.transient != nil || self.reactive.debug != nil) {
                    self.reactive.transient = nil; self.reactive.endPreview(); self.reconcileAnimation(force:true)
                }
            }
            else { self.displayFrame(); self.scheduleFrame() }
        }
        timer.tolerance = min(0.02, cursor.duration*0.1)
        frameTimer = timer; RunLoop.main.add(timer, forMode: .common)
    }
    func makeAnimationMenu() -> NSMenu {
        let menu = NSMenu(title: "动作试播 / Manual preview")
        menu.autoenablesItems = false
        for i in animationNames.indices {
            let item = NSMenuItem(title: animationLabels[i] + " · 试播 / Preview", action: #selector(selectAnimation), keyEquivalent: "")
            item.target = self; item.tag = i; item.isEnabled = availableSequence(animationNames[i]) != nil
            menu.addItem(item)
        }
        return menu
    }
    @objc func selectAnimation(_ sender: NSMenuItem) {
        guard animationNames.indices.contains(sender.tag), let sequence = availableSequence(animationNames[sender.tag]) else { return }
        let seconds = Double(sequence.durationsMS.reduce(0,+))/1000 + (useRecline && PoseArbiter.standingActions.contains(animationNames[sender.tag]) ? 0.64 : 0)
        reactive.beginPreview(animationNames[sender.tag],duration:seconds,now:ProcessInfo.processInfo.systemUptime)
        reconcileAnimation(force:true); writePlaybackState("manual_preview_started")
        sound.chime("open")
    }
    @objc func showAnimationMenu(_ sender: NSButton) {
        makeAnimationMenu().popUp(positioning: nil, at: NSPoint(x: 0, y: sender.bounds.maxY), in: sender)
    }
    func rebuildMenu() {
        guard status != nil, wardrobe != nil else { return }
        let menu = NSMenu()
        @discardableResult func item(_ title: String, _ action: Selector?, key: String = "") -> NSMenuItem {
            let i = NSMenuItem(title: title, action: action, keyEquivalent: key)
            i.target = self; menu.addItem(i); return i
        }
        item("夜璃 · Nyra  /  1.0 · 互动桌宠 / Reactive companion", nil)
        item("显示 / 隐藏 · Show / Hide", #selector(toggleVisibility))
        item("动作与换装 / Actions and outfits", #selector(showStage))
        item("透明舞台 / 返回 · Transparent stage / Back", #selector(fullscreen))
        item("一键换装 / Next outfit", #selector(nextOutfit))
        let wardrobeItem = item("服装 / Outfit", nil)
        let outfits = NSMenu()
        for (index,outfit) in wardrobe.outfits.enumerated() {
            let i = NSMenuItem(title: outfit.name, action: #selector(selectOutfit), keyEquivalent: "")
            i.target = self; i.tag = index; i.state = index == selected ? .on : .off; outfits.addItem(i)
        }
        wardrobeItem.submenu = outfits
        menu.addItem(.separator())
        item("放大 / Larger", #selector(larger)); item("缩小 / Smaller", #selector(smaller))
        item("复位位置 / Reset position", #selector(resetPosition))
        let passthrough = item("整窗穿透 / Pass through (restore from menu bar)", #selector(togglePassThrough))
        passthrough.state = passThrough ? .on : .off
        menu.addItem(.separator())
        item("SIMULATION · 状态文字示例", nil).submenu = makeDemoMenu()
        item("动作试播 / Manual animation preview", nil).submenu = makeAnimationMenu()
        item("TWOS：\(live.connectionLabel)", nil)
        item("连接 TWOS 状态 / Connect read-only status…", #selector(configureBridge))
        item("断开 TWOS 状态 / Disconnect status", #selector(disconnectBridge))
        item(sound.isMuted ? "声音：已静音" : "声音设置 · 中英试听 / 音量", #selector(showSoundFromMenu))
        item(NSWorkspace.shared.accessibilityDisplayShouldReduceMotion ? "系统减少动态：显示母版" : "动画：隐藏时停止计时", nil)
        menu.addItem(.separator())
        item("退出 / Quit", #selector(quit), key: "q")
        status.menu = menu
        NSApp.mainMenu?.items.first?.submenu = menu.copy() as? NSMenu
    }

    func saveSettings() {
        guard panel != nil, wardrobe != nil else { return }
        let data: [String: Any] = ["interaction_version": 4, "outfit": wardrobe.outfits[selected].id, "height": desiredHeight,
                                   "x": panel.frame.minX, "y": panel.frame.minY,
                                   "muted": sound.isMuted, "volume": sound.volume, "language": sound.language]
        if let bytes = try? JSONSerialization.data(withJSONObject: data, options: [.prettyPrinted, .sortedKeys]) {
            try? bytes.write(to: prefsURL, options: .atomic)
        }
    }
    func restoreSettings() {
        guard let data = try? Data(contentsOf: prefsURL),
              let prefs = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return }
        if let id = prefs["outfit"] as? String, id != "v3-master", let index = wardrobe.outfits.firstIndex(where: { $0.id == id }) { selected = index }
        if let muted = prefs["muted"] as? Bool { sound.isMuted = muted }
        if let volume = prefs["volume"] as? Float { sound.volume = min(1,max(0,volume)) }
        if let language = prefs["language"] as? String, ["auto","zh","en"].contains(language) { sound.language = language }
        if let height = prefs["height"] as? Double, height.isFinite { desiredHeight = min(max(height, 160), 1000) }
        if prefs["interaction_version"] == nil { desiredHeight = max(400, desiredHeight) }
        if let x = prefs["x"] as? Double, let y = prefs["y"] as? Double, x.isFinite, y.isFinite {
            panel.setFrameOrigin(NSPoint(x: x, y: y))
        }
        clampPanel()
    }
    @objc func quit() { NSApp.terminate(nil) }
    func applicationWillTerminate(_ notification: Notification) {
        stopFrameTimer(); frameImages.removeAll(); hoverTimer?.invalidate(); hoverTimer = nil; sound.stop()
        writePlaybackState("terminating")
        if let observer = screenObserver { NotificationCenter.default.removeObserver(observer) }
        if let observer = motionObserver { NSWorkspace.shared.notificationCenter.removeObserver(observer) }
        livePollTimer?.invalidate(); live.stop()
        if let observer = sleepObserver { NSWorkspace.shared.notificationCenter.removeObserver(observer) }
        if let observer = wakeObserver { NSWorkspace.shared.notificationCenter.removeObserver(observer) }
        restoreDesktopPlacement(); saveSettings()
        panel.orderOut(nil); stage?.orderOut(nil); liveReducer.disconnect(); reactive.connected = false; publishVisibility(persistPreference:false)
        if lockFD >= 0 { flock(lockFD, LOCK_UN); close(lockFD); lockFD = -1 }
        if status != nil { NSStatusBar.system.removeStatusItem(status) }
    }
}

if CommandLine.arguments.contains("--self-test") {
    do {
        try runCoreTests()
        let data = try Data(contentsOf: Bundle.main.resourceURL!.appendingPathComponent("runtime/standalone_r3.json"))
        try runRuntimeTests(JSONDecoder().decode(RuntimePlan.self, from: data))
        try runInteractionTests()
        try runReactiveTests()
        let library = try JSONDecoder().decode(R4Library.self,from:Data(contentsOf:Bundle.main.resourceURL!.appendingPathComponent("runtime/r4.json"))).validated()
        for set in library.sets.values {
            guard set.resolve("not_a_supported_action").0 == "idle" else { throw PreviewError.invalidManifest }
        }
        try runStatusTransportTests()
        print("PASS: R4 outfit/pose containment, missing action fallback stays in selected wardrobe")
    } catch { fputs("FAIL: \(error)\n", stderr); exit(1) }
} else {
    let app = NSApplication.shared
    let companion = Companion()
    app.delegate = companion
    app.run()
}
