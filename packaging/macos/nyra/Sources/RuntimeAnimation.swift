import Foundation

struct FrameSequence: Decodable {
    let loop: Bool
    let assetIDs: [String]
    let durationsMS: [Int]
    enum CodingKeys: String, CodingKey {
        case loop
        case assetIDs = "asset_ids"
        case durationsMS = "durations_ms"
    }
}

struct RuntimePlan: Decodable {
    let sequences: [String: FrameSequence]
    func validated() throws -> RuntimePlan {
        let p0 = ["idle": 6, "working": 6, "gaze_head": 5, "verified_success": 6]
        let extended = ["running_right": 8, "running_left": 8, "waving": 4, "jumping": 5,
                        "failed": 8, "waiting": 6, "review": 6, "look_around": 16]
        let expected = sequences.count == 4 ? p0 : p0.merging(extended) { a, _ in a }
        guard Set(sequences.keys) == Set(expected.keys) else { throw PreviewError.invalidManifest }
        for (name, seq) in sequences {
            guard seq.assetIDs.count == expected[name], seq.durationsMS.count == seq.assetIDs.count,
                  seq.durationsMS.allSatisfy({ $0 > 0 && $0 <= 10000 }),
                  seq.assetIDs.allSatisfy({ !$0.isEmpty && $0.count < 80 && $0.unicodeScalars.allSatisfy({
                      CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyz0123456789_").contains($0)
                  }) }) else { throw PreviewError.invalidManifest }
        }
        guard sequences["idle"]!.loop, sequences["working"]!.loop,
              !sequences["gaze_head"]!.loop, !sequences["verified_success"]!.loop,
              sequences["verified_success"]!.assetIDs.first == "nyra_neutral",
              sequences["verified_success"]!.assetIDs.last == "nyra_neutral",
              Set(p0.keys.flatMap { sequences[$0]!.assetIDs }).count == 20 else { throw PreviewError.invalidManifest }
        if sequences.count > 4 {
            guard Set(sequences.values.flatMap(\.assetIDs)).count == 77,
                  sequences["running_right"]!.loop, sequences["running_left"]!.loop,
                  !sequences["jumping"]!.loop, !sequences["waving"]!.loop else { throw PreviewError.invalidManifest }
        }
        return self
    }
}

struct FrameCursor {
    let sequence: FrameSequence
    private(set) var index = 0
    private(set) var finished = false
    var assetID: String { sequence.assetIDs[index] }
    var duration: TimeInterval { Double(sequence.durationsMS[index]) / 1000 }
    mutating func advance() {
        guard !finished else { return }
        if index + 1 < sequence.assetIDs.count { index += 1 }
        else if sequence.loop { index = 0 }
        else { finished = true }
    }
}

func runRuntimeTests(_ plan: RuntimePlan) throws {
    _ = try plan.validated()
    var success = FrameCursor(sequence: plan.sequences["verified_success"]!)
    var seen: [String] = []
    for _ in 0..<6 { seen.append(success.assetID); success.advance() }
    guard seen == plan.sequences["verified_success"]!.assetIDs,
          success.finished, success.assetID == "nyra_neutral" else { throw PreviewError.invalidManifest }
    let last = success.index; success.advance()
    guard success.index == last else { throw PreviewError.invalidManifest }
    var idle = FrameCursor(sequence: plan.sequences["idle"]!)
    for _ in 0..<12 { idle.advance() }
    guard !idle.finished, idle.index == 0 else { throw PreviewError.invalidManifest }
    print("PASS: runtime sequence containment, 20 unique / 23 slots, once-only success, idle loop")
}
