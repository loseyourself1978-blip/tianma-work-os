import AppKit

final class OrbitButton: NSButton {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override func draw(_ dirtyRect: NSRect) {
        let circle = NSBezierPath(ovalIn: bounds.insetBy(dx: 1, dy: 1))
        NSColor(calibratedRed: 0.16, green: 0.10, blue: 0.24, alpha: isHighlighted ? 1 : 0.94).setFill()
        circle.fill()
        violet.withAlphaComponent(isHighlighted ? 1 : 0.7).setStroke()
        circle.lineWidth = isHighlighted ? 2 : 1; circle.stroke()
        if let image = image {
            image.draw(in: bounds.insetBy(dx: 10, dy: 10), from: .zero, operation: .sourceOver, fraction: 1,
                       respectFlipped: true, hints: nil)
        } else {
            let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 21, weight: .light), .foregroundColor: NSColor.white]
            let size = title.size(withAttributes: attrs)
            title.draw(at: NSPoint(x: bounds.midX-size.width/2, y: bounds.midY-size.height/2), withAttributes: attrs)
        }
    }
}

func orbitButton(_ symbol: String, title: String, target: AnyObject, action: Selector) -> OrbitButton {
    let b = OrbitButton(title: title, target: target, action: action)
    b.isBordered = false
    if let image = NSImage(systemSymbolName: symbol, accessibilityDescription: title) {
        b.image = image.withSymbolConfiguration(.init(paletteColors: [.white]))
    }
    b.toolTip = title; b.setAccessibilityLabel(title)
    return b
}

final class ResizeGrip: NSView {
    var onBegin: (() -> Void)?
    var onResize: ((CGFloat) -> Void)?
    var onEnd: (() -> Void)?
    private var start: NSPoint?
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    override init(frame: NSRect) {
        super.init(frame: frame)
        toolTip = "拖动缩放 / Drag to resize · 滚轮 / Scroll"
        setAccessibilityElement(true); setAccessibilityRole(.button); setAccessibilityLabel("拖动缩放 / Drag to resize")
    }
    required init?(coder: NSCoder) { fatalError() }
    override func draw(_ dirtyRect: NSRect) {
        let p = NSBezierPath(ovalIn: bounds.insetBy(dx: 1, dy: 1)); ink.withAlphaComponent(0.9).setFill(); p.fill()
        violet.setStroke(); p.lineWidth = 1; p.stroke()
        NSImage(systemSymbolName: "ruler", accessibilityDescription: nil)?
            .withSymbolConfiguration(.init(paletteColors: [.white]))?
            .draw(in: bounds.insetBy(dx: 8, dy: 8))
    }
    override func mouseDown(with event: NSEvent) { start = window?.convertPoint(toScreen: event.locationInWindow); onBegin?() }
    override func mouseDragged(with event: NSEvent) {
        guard let start = start else { return }
        guard let point = window?.convertPoint(toScreen: event.locationInWindow) else { return }
        onResize?(point.x-start.x-(point.y-start.y))
    }
    override func mouseUp(with event: NSEvent) { start = nil; onEnd?() }
}

final class PanelView: NSView {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
    let art = ArtView()
    let badge = text("夜璃 · Nyra", size: 11, color: violet)
    let detail = text("悬停 + 展开控制", size: 10, color: .white)
    let grip = ResizeGrip(frame: .zero)
    var hub: OrbitButton!
    var stageButton: OrbitButton!
    var onStage: (() -> Void)?
    var controls: [NSButton] = []
    var expanded = false
    private(set) var hovered = false
    var onDragEnd: (() -> Void)?
    override init(frame: NSRect) {
        super.init(frame: frame)
        for v in [art, badge, detail, grip] as [NSView] { addSubview(v) }
        for label in [badge,detail] {
            label.drawsBackground = true; label.backgroundColor = ink.withAlphaComponent(0.90)
            label.wantsLayer = true; label.layer?.cornerRadius = 5
        }
        grip.isHidden = true; badge.isHidden = true; detail.isHidden = true
    }
    required init?(coder: NSCoder) { fatalError() }
    func configureHub() {
        hub = orbitButton("plus", title: "展开夜璃控制环", target: self, action: #selector(toggleControls))
        addSubview(hub)
        stageButton = orbitButton("arrow.up.left.and.arrow.down.right", title: "进入人物全屏 / Enter character stage", target: self, action: #selector(enterStage))
        addSubview(stageButton); refreshVisibility()
    }
    @objc func enterStage() { onStage?() }
    @objc func toggleControls() {
        expanded.toggle()
        hub.image = NSImage(systemSymbolName: expanded ? "xmark" : "plus", accessibilityDescription: nil)?
            .withSymbolConfiguration(.init(paletteColors: [.white]))
        hub.setAccessibilityLabel(expanded ? "收起夜璃控制环" : "展开夜璃控制环")
        refreshVisibility()
    }
    func setHovered(_ value: Bool) { if hovered != value { hovered = value; refreshVisibility() } }
    func refreshVisibility() {
        hub?.alphaValue = hovered || expanded ? 1 : 0.52
        controls.forEach { $0.isHidden = !expanded }
        badge.isHidden = !hovered && !expanded; detail.isHidden = badge.isHidden
        // Do not remove the first-mouse target while a press is tracking.
        let showHoverControls = hovered || expanded || NSEvent.pressedMouseButtons != 0
        grip.isHidden = !showHoverControls
        stageButton?.isHidden = !showHoverControls
        needsLayout = true
    }
    override func layout() {
        super.layout()
        art.frame = NSRect(x: 8, y: 32, width: bounds.width-70, height: bounds.height-52)
        let center = NSPoint(x: bounds.width-89, y: min(145, bounds.height*0.38))
        hub?.frame = NSRect(x: center.x-20, y: center.y-20, width: 40, height: 40)
        for (i,b) in controls.enumerated() {
            let angle = CGFloat(i)*2 * .pi/CGFloat(max(1,controls.count)) + .pi/2
            b.frame = NSRect(x: center.x+67*cos(angle)-18, y: center.y+67*sin(angle)-18, width: 36, height: 36)
        }
        stageButton?.frame = NSRect(x: bounds.width-43, y: 2, width: 36, height: 36)
        grip.frame = NSRect(x: bounds.width-79, y: 5, width: 30, height: 30)
        badge.frame = NSRect(x: 12, y: bounds.height-21, width: bounds.width-24, height: 18)
        detail.frame = NSRect(x: 12, y: 3, width: max(20,bounds.width-98), height: 27)
    }
    func visibleHit(_ point: NSPoint) -> Bool {
        if let hub = hub, hub.frame.contains(point) { return true }
        if let stageButton = stageButton, !stageButton.isHidden && stageButton.frame.contains(point) { return true }
        if !grip.isHidden && grip.frame.contains(point) { return true }
        if expanded && controls.contains(where: { $0.frame.contains(point) }) { return true }
        return art.containsArt(art.convert(point, from: self))
    }
}

final class StageWindow: NSWindow {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
    var onEscape: (() -> Void)?
    override func cancelOperation(_ sender: Any?) { onEscape?() }
}

func runInteractionTests() throws {
    func require(_ condition: Bool) throws { if !condition { throw PreviewError.invalidManifest } }
    try require(NyraAudio.resolveLanguage("auto", preferred: ["zh-Hans-CN"]) == "zh")
    try require(NyraAudio.resolveLanguage("auto", preferred: ["en-GB"]) == "en")
    try require(NyraAudio.resolveLanguage("en", preferred: ["zh-Hans"]) == "en")
    try require(NyraAudio.resolveLanguage("zh", preferred: ["en-US"]) == "zh")
    // A deliberately asymmetric bitmap catches inverted alpha hit testing.
    let context = CGContext(data: nil, width: 64, height: 96, bitsPerComponent: 8, bytesPerRow: 256,
        space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
    context.setFillColor(NSColor.white.cgColor)
    context.fill(CGRect(x: 0, y: 48, width: 32, height: 48))
    let art = ArtView(frame: NSRect(x: 0, y: 0, width: 64, height: 96))
    art.isRuntime = true; art.image = NSImage(cgImage: context.makeImage()!, size: NSSize(width: 64, height: 96))
    try require(art.containsArt(NSPoint(x: 16, y: 72)))
    try require(!art.containsArt(NSPoint(x: 48, y: 72)))
    try require(!art.containsArt(NSPoint(x: 16, y: 24)))
    try require(!art.containsArt(NSPoint(x: -1, y: 72)))
    let panel = PanelView(frame: NSRect(x: 0, y: 0, width: 320, height: 452))
    panel.configureHub(); panel.layoutSubtreeIfNeeded()
    try require(panel.visibleHit(NSPoint(x: panel.hub.frame.midX, y: panel.hub.frame.midY)))
    try require(!panel.visibleHit(NSPoint(x: 1, y: 1)))
    panel.toggleControls(); try require(panel.expanded && !panel.grip.isHidden)
    var stageClicks = 0
    panel.onStage = { stageClicks += 1 }
    panel.setHovered(true); panel.layoutSubtreeIfNeeded()
    try require(!panel.stageButton.isHidden && !panel.grip.isHidden)
    try require(!panel.stageButton.frame.intersects(panel.grip.frame))
    try require(panel.visibleHit(NSPoint(x:panel.stageButton.frame.midX,y:panel.stageButton.frame.midY)))
    let beforeStageClick = panel.frame
    panel.stageButton.performClick(nil)
    try require(stageClicks == 1 && panel.frame == beforeStageClick)
    try require(panel.stageButton.acceptsFirstMouse(for:nil))
    try runStageGeometryTests()
    print("PASS: language, alpha hit testing, hover stage click without resize, distinct resize, safe top toolbar fixtures")
}
