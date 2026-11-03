import Foundation
import CryptoKit

// Fixed, licensed recordings only. No synthesis service, task text or network.
struct BundledVoicePack: Decodable {
    struct Clip: Decodable {
        let file: String
        let sha256: String
        let text: String
    }
    let schema: Int
    let voice_id: String
    let display_name: String
    let language: String
    let clips: [String:Clip]

    static func read(_ root: URL) throws -> BundledVoicePack {
        let file = root.appendingPathComponent("manifest.json")
        guard root.resolvingSymlinksInPath().standardizedFileURL.path == root.standardizedFileURL.path,
              file.resolvingSymlinksInPath().path == file.path else { throw PreviewError.invalidManifest }
        let reader = try FileHandle(forReadingFrom:file); defer { try? reader.close() }
        let data = try reader.read(upToCount:32_768) ?? Data()
        guard data.count < 32_768 else { throw PreviewError.invalidManifest }
        let pack = try JSONDecoder().decode(Self.self,from:data)
        guard pack.schema == 1, pack.voice_id == "ttsmaker:1413:default", pack.language == "zh",
              pack.display_name == "小田 / Tian",
              Set(pack.clips.keys) == Set(VoiceCue.allCases.map(\.rawValue)) else { throw PreviewError.invalidManifest }
        return pack
    }
    func data(_ cue: VoiceCue, root: URL) throws -> Data {
        guard let clip = clips[cue.rawValue], clip.file == cue.rawValue+".wav",
              clip.text == cue.phrase(language), clip.sha256.count == 64 else { throw PreviewError.invalidManifest }
        let file = root.appendingPathComponent(clip.file)
        guard file.resolvingSymlinksInPath().standardizedFileURL.path == file.standardizedFileURL.path else { throw PreviewError.invalidManifest }
        let reader = try FileHandle(forReadingFrom:file); defer { try? reader.close() }
        let data = try reader.read(upToCount:25*1024*1024) ?? Data()
        guard !data.isEmpty, data.count < 25*1024*1024,
              SHA256.hash(data:data).map({ String(format:"%02x",$0) }).joined() == clip.sha256 else { throw PreviewError.invalidManifest }
        return data
    }
}
