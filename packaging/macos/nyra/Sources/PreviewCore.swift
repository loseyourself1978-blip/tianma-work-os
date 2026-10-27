import Foundation
import CoreGraphics

struct Outfit: Decodable {
    let id: String
    let name: String
    let file: String
    let note: String
    let width: Int
    let height: Int
    let runtimeReady: Bool
    var isStaticOutfit: Bool { id.hasPrefix("runtime-") && !runtimeReady }
    var isTransparentArt: Bool { id.hasPrefix("runtime-") }
    var stateLabel: String { runtimeReady ? "P0 ANIMATION · SIMULATION" : isStaticOutfit ? "STATIC_OUTFIT_ONLY" : "STATIC_REFERENCE" }
}

struct Wardrobe: Decodable {
    let schemaVersion: Int
    let character: String
    let mode: String
    let defaultOutfit: String
    let outfits: [Outfit]

    func validated() throws -> Wardrobe {
        guard schemaVersion == 1, !outfits.isEmpty,
              Set(outfits.map(\.id)).count == outfits.count,
              outfits.contains(where: { $0.id == defaultOutfit }) else {
            throw PreviewError.invalidManifest
        }
        for outfit in outfits {
            // References stay references. No arbitrary paths or remote URLs.
            guard outfit.width > 0, outfit.height > 0,
                  !outfit.file.contains("/"), !outfit.file.contains("\\"),
                  !outfit.file.hasPrefix("."), outfit.file.lowercased().hasSuffix(".png") else { throw PreviewError.invalidManifest }
        }
        return self
    }
}

enum PreviewError: Error { case invalidManifest, imageMissing(String) }

enum DemoState: String, CaseIterable {
    case none, received, running, approval, completedUnverified, partial, failed, verified, accepted, disconnected
    var label: String {
        switch self {
        case .none: return "未连接 TWOS · 无实时事件"
        case .received: return "SIMULATION · 已收到指令；尚未开始"
        case .running: return "SIMULATION · 执行中；无真实进度数值"
        case .approval: return "SIMULATION · 等待用户批准；桌宠不能批准"
        case .completedUnverified: return "SIMULATION · 执行结束；业务结果尚未核验"
        case .partial: return "SIMULATION · 部分完成；仍有未完成项"
        case .failed: return "SIMULATION · 失败；等待查看原因"
        case .verified: return "SIMULATION · 验证通过；Owner 尚未接受"
        case .accepted: return "SIMULATION · Owner 接受示例；非实际验收"
        case .disconnected: return "SIMULATION · 已断线；当前状态未知"
        }
    }
    var menuTitle: String {
        switch self {
        case .none: return "关闭模拟 · 未接入"
        case .received: return "收到指令"
        case .running: return "执行中"
        case .approval: return "等待批准"
        case .completedUnverified: return "执行结束 · 未核验"
        case .partial: return "PARTIAL"
        case .failed: return "FAILED"
        case .verified: return "验证通过 · 非 Owner 接受"
        case .accepted: return "Owner 接受示例"
        case .disconnected: return "断线 · 状态未知"
        }
    }
}

enum Geometry {
    static func clamp(_ rect: CGRect, to screen: CGRect) -> CGRect {
        let size = CGSize(width: min(rect.width, screen.width), height: min(rect.height, screen.height))
        return CGRect(x: min(max(rect.minX, screen.minX), screen.maxX-size.width),
                      y: min(max(rect.minY, screen.minY), screen.maxY-size.height),
                      width: size.width, height: size.height)
    }
    static func fit(image: CGSize, in box: CGRect) -> CGRect {
        guard image.width > 0, image.height > 0 else { return .zero }
        let scale = min(box.width/image.width, box.height/image.height)
        let size = CGSize(width: image.width*scale, height: image.height*scale)
        return CGRect(x: box.midX-size.width/2, y: box.midY-size.height/2,
                      width: size.width, height: size.height)
    }
}

func runCoreTests() throws {
    func check(_ value: Bool, _ message: String) {
        if !value { fputs("FAIL: \(message)\n", stderr); exit(1) }
    }
    let screen = CGRect(x: -1440, y: 0, width: 1440, height: 900)
    let clamped = Geometry.clamp(CGRect(x: 1000, y: -200, width: 300, height: 400), to: screen)
    check(screen.contains(clamped), "restore offscreen panel to a negative-origin display")
    let large = Geometry.clamp(CGRect(x: 100, y: 100, width: 4000, height: 4000), to: screen)
    check(large == screen, "oversized panel remains reachable")
    let fitted = Geometry.fit(image: CGSize(width: 302, height: 517), in: CGRect(x: 0, y: 0, width: 1000, height: 700))
    check(abs(fitted.width/fitted.height-302.0/517.0) < 0.0001, "fullscreen preserves aspect ratio")
    check(DemoState.completedUnverified.label.contains("尚未核验"), "completed does not imply verified")
    check(DemoState.verified.label.contains("尚未接受"), "verification differs from acceptance")
    check(DemoState.allCases.dropFirst().allSatisfy { $0.label.contains("SIMULATION") }, "all examples labelled")
    let unsafe = Wardrobe(schemaVersion: 1, character: "Nyra", mode: "STATIC_PREVIEW", defaultOutfit: "x",
                         outfits: [Outfit(id: "x", name: "x", file: "../../secret.png", note: "", width: 1, height: 1, runtimeReady: false)])
    do { _ = try unsafe.validated(); check(false, "path traversal rejected") } catch {}
    print("PASS: 7 core checks (geometry, aspect ratio, truth labels, manifest containment)")
}
