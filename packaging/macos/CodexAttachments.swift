import Foundation
import PDFKit

enum CodexAttachmentFailure: String, Error {
    case unsupported, unreadable, tooLarge, encoding, malformed, encrypted, empty, unsafeArchive, tooComplex
    var message: String {
        switch self {
        case .unsupported: return "Unsupported attachment format. Choose text/code, Markdown, JSON, CSV, HTML, PNG/JPEG, PDF, DOCX, XLSX or PPTX."
        case .unreadable: return "The selected attachment cannot be read. Check its file permission."
        case .tooLarge: return "Attachment limit: 8 MB per source file, 12 MB per message, and 200 KB of extracted text per file. Nothing was silently truncated."
        case .encoding: return "Text encoding is unsupported or invalid. Use UTF-8 or BOM-marked UTF-16 text."
        case .malformed: return "This attachment could not be parsed as its declared format. It has not been attached."
        case .encrypted: return "Encrypted or password-protected documents cannot be read here. No password was requested."
        case .empty: return "No readable text was found. Scanned PDF images require OCR, which this client does not provide."
        case .unsafeArchive: return "This Office document contains unsafe paths, macro content or an unsupported package structure. It has not been attached."
        case .tooComplex: return "The document exceeds the local parser's page, entry, time or expansion limit. It has not been attached."
        }
    }
}
struct CodexParsedAttachment {
    var bytes: Data
    var mime: String
    var coverage: String
    var sourceBytes: Int
    var sourceHash: String
}
final class CodexXMLText: NSObject, XMLParserDelegate {
    var text = "", chunks: [String] = [], shared: [String] = []
    var element = "", cellType = "", cell = "", cellValue = "", cellFormula = ""
    let mode: String
    var bad = false
    var textBytes = 0
    init(mode: String, shared: [String] = []) { self.mode = mode; self.shared = shared }
    func parser(_ parser: XMLParser, didStartElement name: String, namespaceURI: String?, qualifiedName: String?, attributes a: [String: String]) {
        element = name.components(separatedBy: ":").last ?? name
        if element == "si" { text = "" }
        if mode == "sheet", element == "c" { cell = a["r"] ?? "?"; cellType = a["t"] ?? ""; cellValue = ""; cellFormula = "" }
    }
    func parser(_ parser: XMLParser, foundCharacters value: String) {
        if mode == "sheet" {
            if element == "v" || element == "t" { cellValue += value }
            if element == "f" { cellFormula += value }
        } else if element == "t" { text += value }
        textBytes += value.utf8.count
        if textBytes > 400_000 || text.utf8.count + cellValue.utf8.count > 200_000 { bad = true; parser.abortParsing() }
    }
    func parser(_ parser: XMLParser, didEndElement name: String, namespaceURI: String?, qualifiedName: String?) {
        let local = name.components(separatedBy: ":").last ?? name
        if mode == "shared", local == "si" { chunks.append(text); text = "" }
        else if mode == "sheet", local == "c" {
            if cellType == "s" {
                guard let i = Int(cellValue), shared.indices.contains(i) else { bad = true; parser.abortParsing(); return }
                cellValue = shared[i]
            }
            chunks.append(cell + ": " + cellValue + (cellFormula.isEmpty ? "" : " [formula text, not executed: " + cellFormula + "]"))
        } else if local == "p" || local == "tr" || local == "br" { text += "\n" }
        element = ""
    }
    static func parse(_ data: Data, mode: String, shared: [String] = []) throws -> [String] {
        guard data.count <= 2_000_000, let xml = String(data: data, encoding: .utf8), !xml.localizedCaseInsensitiveContains("<!DOCTYPE"), !xml.localizedCaseInsensitiveContains("<!ENTITY") else { throw CodexAttachmentFailure.malformed }
        let reader = CodexXMLText(mode: mode, shared: shared), parser = XMLParser(data: data)
        parser.shouldResolveExternalEntities = false; parser.delegate = reader
        guard parser.parse(), !reader.bad else { throw CodexAttachmentFailure.malformed }
        return mode == "shared" || mode == "sheet" ? reader.chunks : [reader.text]
    }
}
enum CodexAttachmentParser {
    static let textExtensions = ["txt", "md", "markdown", "json", "csv", "tsv", "html", "htm", "css", "js", "ts", "tsx", "jsx", "py", "swift", "sh", "bash", "zsh", "yaml", "yml", "toml", "xml", "sql", "c", "h", "cpp", "rs", "go", "java", "r", "rb", "vue", "svelte", "log"]
    static let extensions = textExtensions + ["png", "jpg", "jpeg", "pdf", "docx", "xlsx", "pptx"]
    static func validateOfficeArchive(_ bytes: Data) throws {
        func u16(_ at: Int) -> Int { Int(bytes[at]) | Int(bytes[at + 1]) << 8 }
        func u32(_ at: Int) -> Int { u16(at) | u16(at + 2) << 16 }
        guard bytes.count >= 22 else { throw CodexAttachmentFailure.malformed }
        let end = stride(from: bytes.count - 22, through: max(0, bytes.count - 65_557), by: -1).first {
            u32($0) == 0x06054b50 && $0 + 22 + u16($0 + 20) == bytes.count
        }
        guard let end = end, u16(end + 4) == 0, u16(end + 6) == 0, u16(end + 8) == u16(end + 10) else { throw CodexAttachmentFailure.malformed }
        let count = u16(end + 10); var cursor = u32(end + 16)
        guard count > 0, count <= 1500, cursor >= 0, cursor < end else { throw CodexAttachmentFailure.tooComplex }
        for _ in 0..<count {
            guard cursor + 46 <= end, u32(cursor) == 0x02014b50 else { throw CodexAttachmentFailure.malformed }
            guard u16(cursor + 8) & 1 == 0 else { throw CodexAttachmentFailure.encrypted }
            guard [0, 8].contains(u16(cursor + 10)), u32(cursor + 24) != 0xffffffff else { throw CodexAttachmentFailure.tooComplex }
            // Reject Unix symlink members; nothing is extracted to the filesystem.
            guard (u32(cursor + 38) >> 16) & 0xf000 != 0xa000 else { throw CodexAttachmentFailure.unsafeArchive }
            cursor += 46 + u16(cursor + 28) + u16(cursor + 30) + u16(cursor + 32)
            guard cursor <= end else { throw CodexAttachmentFailure.malformed }
        }
    }
    // Executes one fixed OS parser command with explicit arguments, never a shell
    // or document content. Bounded streaming avoids zip bombs and blocking the UI.
    static func unzip(_ file: URL, arguments: [String], limit: Int) throws -> Data {
        let process = Process(), pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
        process.arguments = arguments + [file.path]
        if arguments.first == "-p", arguments.count == 2 { process.arguments = ["-p", file.path, arguments[1]] }
        process.standardOutput = pipe; process.standardError = FileHandle.nullDevice
        let lock = NSLock(), group = DispatchGroup(); var data = Data(), overflow = false
        try process.run(); group.enter()
        DispatchQueue.global(qos: .utility).async {
            while true {
                let next = pipe.fileHandleForReading.availableData
                if next.isEmpty { break }
                lock.lock()
                if data.count + next.count > limit { overflow = true; lock.unlock(); if process.isRunning { process.terminate() }; break }
                data.append(next); lock.unlock()
            }
            group.leave()
        }
        guard group.wait(timeout: .now() + 4) == .success else { if process.isRunning { process.terminate() }; throw CodexAttachmentFailure.tooComplex }
        process.waitUntilExit(); lock.lock(); defer { lock.unlock() }
        guard !overflow else { throw CodexAttachmentFailure.tooComplex }
        guard process.terminationStatus == 0 else { throw CodexAttachmentFailure.malformed }
        return data
    }
    static func parse(name: String, bytes: Data, scratch: URL) throws -> CodexParsedAttachment {
        guard !bytes.isEmpty else { throw CodexAttachmentFailure.empty }
        guard bytes.count <= 8_000_000 else { throw CodexAttachmentFailure.tooLarge }
        let ext = URL(fileURLWithPath: name).pathExtension.lowercased()
        var text = "", coverage = "", mime = "text/plain"
        let deadline = ProcessInfo.processInfo.systemUptime + 15
        if textExtensions.contains(ext) {
            if bytes.starts(with: [0xff, 0xfe]) || bytes.starts(with: [0xfe, 0xff]) { text = String(data: bytes, encoding: .utf16) ?? "" }
            else { text = String(data: bytes, encoding: .utf8) ?? "" }
            guard !text.isEmpty, !text.contains("\0") else { throw CodexAttachmentFailure.encoding }
            coverage = "text_full"
        } else if ["png", "jpeg", "jpg"].contains(ext) {
            guard (bytes.starts(with: [0x89, 0x50, 0x4e, 0x47]) || bytes.starts(with: [0xff, 0xd8, 0xff])),
                  let rep = NSBitmapImageRep(data: bytes), rep.pixelsWide > 0, rep.pixelsHigh > 0,
                  rep.pixelsWide <= 16000, rep.pixelsHigh <= 16000, rep.pixelsWide * rep.pixelsHigh <= 40_000_000 else { throw CodexAttachmentFailure.malformed }
            mime = bytes.starts(with: [0x89, 0x50, 0x4e, 0x47]) ? "image/png" : "image/jpeg"
            return CodexParsedAttachment(bytes: bytes, mime: mime, coverage: "image_native", sourceBytes: bytes.count, sourceHash: NativeCodex.digest(bytes))
        } else if ext == "pdf" {
            guard bytes.starts(with: Data("%PDF-".utf8)), let document = PDFDocument(data: bytes) else { throw CodexAttachmentFailure.malformed }
            guard !document.isLocked else { throw CodexAttachmentFailure.encrypted }
            guard document.pageCount <= 200 else { throw CodexAttachmentFailure.tooComplex }
            var readable = 0
            for index in 0..<document.pageCount {
                guard ProcessInfo.processInfo.systemUptime < deadline else { throw CodexAttachmentFailure.tooComplex }
                let page = document.page(at: index)?.string ?? ""
                if !page.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { readable += 1; text += "\n[Page \(index + 1)]\n" + page }
                if text.utf8.count > 200_000 { throw CodexAttachmentFailure.tooLarge }
            }
            guard readable > 0 else { throw CodexAttachmentFailure.empty }
            coverage = "pdf_text:\(readable)/\(document.pageCount)"
        } else if ["docx", "xlsx", "pptx"].contains(ext) {
            guard bytes.starts(with: [0x50, 0x4b]) else { throw CodexAttachmentFailure.malformed }
            try validateOfficeArchive(bytes)
            try NativeWorkbench.safeDirectory(scratch)
            let file = scratch.appendingPathComponent(UUID().uuidString + "." + ext)
            try bytes.write(to: file, options: .atomic)
            defer { try? FileManager.default.removeItem(at: file) }
            let list = try unzip(file, arguments: ["-Z1"], limit: 256_000)
            guard let listing = String(data: list, encoding: .utf8) else { throw CodexAttachmentFailure.malformed }
            let entries = listing.split(separator: "\n").map(String.init)
            guard entries.count <= 1500, Set(entries).count == entries.count, entries.contains("[Content_Types].xml"),
                  !entries.contains(where: { $0.hasPrefix("/") || $0.contains("\\") || $0.split(separator: "/").contains("..") || $0.lowercased().contains("vbaproject") }) else { throw CodexAttachmentFailure.unsafeArchive }
            func read(_ path: String, mode: String = "text", shared: [String] = []) throws -> [String] {
                guard entries.contains(path) else { throw CodexAttachmentFailure.malformed }
                return try CodexXMLText.parse(unzip(file, arguments: ["-p", path], limit: 2_000_000), mode: mode, shared: shared)
            }
            if ext == "docx" { text = try read("word/document.xml").joined(separator: "\n"); coverage = "docx_body_tables_text" }
            else {
                let pattern = ext == "xlsx" ? #"^xl/worksheets/sheet[0-9]+\.xml$"# : #"^ppt/slides/slide[0-9]+\.xml$"#
                let pages = entries.filter { $0.range(of: pattern, options: .regularExpression) != nil }.sorted { $0.localizedStandardCompare($1) == .orderedAscending }
                guard !pages.isEmpty, pages.count <= 200 else { throw CodexAttachmentFailure.tooComplex }
                let shared = ext == "xlsx" && entries.contains("xl/sharedStrings.xml") ? try read("xl/sharedStrings.xml", mode: "shared") : []
                for page in pages {
                    guard ProcessInfo.processInfo.systemUptime < deadline else { throw CodexAttachmentFailure.tooComplex }
                    text += "\n[\(page)]\n" + (try read(page, mode: ext == "xlsx" ? "sheet" : "text", shared: shared)).joined(separator: "\n")
                    if text.utf8.count > 200_000 { throw CodexAttachmentFailure.tooLarge }
                }
                coverage = ext == "xlsx" ? "xlsx_cells_cached_formula_text:\(pages.count)" : "pptx_slide_text:\(pages.count)"
            }
        } else { throw CodexAttachmentFailure.unsupported }
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { throw CodexAttachmentFailure.empty }
        guard text.utf8.count <= 200_000 else { throw CodexAttachmentFailure.tooLarge }
        return CodexParsedAttachment(bytes: Data(text.utf8), mime: mime, coverage: coverage, sourceBytes: bytes.count, sourceHash: NativeCodex.digest(bytes))
    }
}
