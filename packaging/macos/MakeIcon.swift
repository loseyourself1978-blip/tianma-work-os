import AppKit
import Foundation

// Deterministic vector artwork rendered at all macOS icon sizes at build time.
let output = URL(fileURLWithPath: CommandLine.arguments[1])
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)
for size in [16, 32, 128, 256, 512] {
    for scale in [1, 2] {
        let pixels = size * scale
        let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                                  bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                                  isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
        NSGraphicsContext.saveGraphicsState()
        NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
        let p = CGFloat(pixels)
        let shape = NSBezierPath(roundedRect: NSRect(x: p * 0.08, y: p * 0.08, width: p * 0.84, height: p * 0.84), xRadius: p * 0.19, yRadius: p * 0.19)
        NSColor(calibratedRed: 0.12, green: 0.24, blue: 0.52, alpha: 1).setFill()
        shape.fill()
        NSColor.white.setFill()
        NSBezierPath(roundedRect: NSRect(x: p * 0.26, y: p * 0.63, width: p * 0.48, height: p * 0.12), xRadius: p * 0.025, yRadius: p * 0.025).fill()
        NSBezierPath(roundedRect: NSRect(x: p * 0.44, y: p * 0.28, width: p * 0.12, height: p * 0.41), xRadius: p * 0.025, yRadius: p * 0.025).fill()
        NSColor(calibratedRed: 0.35, green: 0.83, blue: 0.77, alpha: 1).setFill()
        NSBezierPath(roundedRect: NSRect(x: p * 0.65, y: p * 0.26, width: p * 0.13, height: p * 0.13), xRadius: p * 0.04, yRadius: p * 0.04).fill()
        NSGraphicsContext.restoreGraphicsState()
        let suffix = scale == 2 ? "@2x" : ""
        try rep.representation(using: .png, properties: [:])!.write(to: output.appendingPathComponent("icon_\(size)x\(size)\(suffix).png"))
    }
}
