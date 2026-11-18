import Darwin
import Foundation

enum TeamError: String, Error {
  case invalidInput, invalidReply, invalidReport, invalidReview, missingIdentity, wrongVersion
  case budgetExceeded, changedDirectory, alreadyExported, storage, busy, unavailable
}

struct TeamText: Codable, Equatable {
  let en: String
  let zh: String
  var valid: Bool {
    [en, zh].allSatisfy {
      !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && $0.utf8.count <= 8000
    }
  }
}
struct TeamRow: Codable, Equatable {
  let region: String
  let cents: Int
}
struct TeamReport: Codable {
  let title: TeamText
  let summary: TeamText
  let rows: [TeamRow]
  let totalCents: Int
}
struct TeamReview: Codable {
  let digest: String
  let verdict: String
  let findings: TeamText
}
struct TeamPlan: Codable {
  let builder: TeamText
  let reviewer: TeamText
  let acceptance: TeamText
}
enum TeamFiles {
  static let sample = "region,amount\nEast,1200.00\nSouth,1800.00\nEast,2000.00"
  static func bytes<T: Encodable>(_ value: T) throws -> Data {
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
    return try encoder.encode(value)
  }
  static func json<T: Encodable>(_ value: T) throws -> String {
    String(decoding: try bytes(value), as: UTF8.self)
  }
  static func decode<T: Decodable>(_ type: T.Type, _ text: String) throws -> T {
    var s = text.trimmingCharacters(in: .whitespacesAndNewlines)
    if s.hasPrefix("\u{60}\u{60}\u{60}json\n"), s.hasSuffix("\n\u{60}\u{60}\u{60}") {
      s = String(s.dropFirst(8).dropLast(4))
    }
    return try JSONDecoder().decode(type, from: Data(s.utf8))
  }
  // A web renderer can smarten JSON delimiters outside a code block. Decode
  // strict JSON first so typographic punctuation in ordinary text stays intact.
  // Only Planner/Builder web content may use this fallback; verdicts never do.
  static func decodeWebContent<T: Decodable>(_ type: T.Type, _ text: String) throws -> T {
    if let strict = try? decode(type, text) { return strict }
    guard text.utf8.count <= 180_000, text.contains("“") || text.contains("”") else {
      throw TeamError.invalidReply
    }
    let chars = Array(text)
    var result = "", inside = false, escaped = false
    var previous: Character?
    for i in chars.indices {
      let c = chars[i]
      var out = c
      if escaped { escaped = false }
      else if inside && c == "\\" { escaped = true }
      else if c == "\"" { inside.toggle() }
      else if c == "“" || c == "”" {
        if inside {
          var j = i + 1
          while j < chars.count && chars[j].isWhitespace { j += 1 }
          if j < chars.count && ",:}]".contains(chars[j]) { out = "\""; inside = false }
        } else if let p = previous, "{[:,".contains(p) { out = "\""; inside = true }
      }
      result.append(out)
      if !c.isWhitespace { previous = out }
    }
    guard !inside && !escaped else { throw TeamError.invalidReply }
    return try decode(type, result)
  }
  // R1's explicit input contract is two columns, whole lines, and exact decimal cents.
  static func totals(_ csv: String) throws -> [String: Int] {
    try sales(csv).mapValues(\.cents)
  }
  private static func sales(_ csv: String) throws -> [String: (count: Int, cents: Int)] {
    guard csv.utf8.count <= 24000 else { throw TeamError.invalidInput }
    let lines = csv.replacingOccurrences(of: "\r\n", with: "\n").split(separator: "\n")
    guard (2...201).contains(lines.count), ["region,amount", "区域,金额"].contains(String(lines[0]))
    else { throw TeamError.invalidInput }
    var result: [String: (count: Int, cents: Int)] = [:]
    for line in lines.dropFirst() {
      let cells = line.split(separator: ",", omittingEmptySubsequences: false)
      guard cells.count == 2 else { throw TeamError.invalidInput }
      let region = cells[0].trimmingCharacters(in: .whitespaces)
      let amount = String(cells[1]).trimmingCharacters(in: .whitespaces)
      guard !region.isEmpty, region.utf8.count <= 80, !region.contains("\""),
        !region.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains),
        amount.range(of: #"^[0-9]{1,9}(\.[0-9]{1,2})?$"#, options: .regularExpression) != nil
      else { throw TeamError.invalidInput }
      let parts = amount.split(separator: ".")
      guard let whole = Int(parts[0]) else { throw TeamError.invalidInput }
      let fraction = parts.count == 2 ? Int(parts[1])! * (parts[1].count == 1 ? 10 : 1) : 0
      result[region, default: (0, 0)].count += 1
      result[region, default: (0, 0)].cents += whole * 100 + fraction
    }
    return result
  }
  static func verify(_ report: TeamReport, csv: String) throws -> Bool {
    let expected = try totals(csv)
    guard report.rows.count == expected.count,
      Set(report.rows.map(\.region)).count == report.rows.count,
      report.rows.allSatisfy({ expected[$0.region] == $0.cents })
    else { return false }
    return expected.values.reduce(0, +) == report.totalCents
  }
  static func money(_ n: Int) -> String {
    let whole = (n / 100).formatted(.number.locale(Locale(identifier: "en_US")))
    return whole + String(format: ".%02lld", Int64(n % 100))
  }
  static func html(_ s: String) -> String {
    s.replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
      .replacingOccurrences(of: ">", with: "&gt;").replacingOccurrences(of: "\"", with: "&quot;")
  }
  static func artifacts(_ report: TeamReport, csv: String) throws -> [String: String] {
    guard report.title.valid, report.summary.valid, (1...200).contains(report.rows.count),
      report.totalCents >= 0,
      report.rows.allSatisfy({ !$0.region.isEmpty && $0.region.utf8.count <= 80 && $0.cents >= 0 })
    else { throw TeamError.invalidReport }
    let source = try sales(csv)
    let count = source.values.reduce(0) { $0 + $1.count }
    let table = report.rows.map {
      "<tr><td>\(html($0.region))</td><td>\(source[$0.region]?.count.description ?? "—")</td><td>\(money($0.cents))</td></tr>"
    }.joined()
    let dashboard = """
      <!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none';style-src 'unsafe-inline'"><title>\(html(report.title.en))</title><style>body{max-width:54rem;margin:3rem auto;padding:0 1rem;font:17px/1.55 system-ui;color:#233d32}table{width:100%;border-collapse:collapse}th,td{padding:.5rem;text-align:left;border-bottom:1px solid #ccd8cf}</style><h1>\(html(report.title.en))<br><span lang="zh-CN">\(html(report.title.zh))</span></h1><table><thead><tr><th>Region / 区域</th><th>Records / 笔数</th><th>Sales / 销售额</th></tr></thead><tbody>\(table)</tbody><tfoot><tr><th>Total / 总额</th><td>\(count)</td><td>\(money(report.totalCents))</td></tr></tfoot></table><p>\(html(report.summary.en))</p><p lang="zh-CN">\(html(report.summary.zh))</p></html>
      """
    return [
      "dashboard.html": dashboard,
      "summary.md":
        "# \(report.title.en)\n\n\(report.summary.en)\n\n# \(report.title.zh)\n\n\(report.summary.zh)\n\nTotal / 总额  \(money(report.totalCents))\n",
    ]
  }
  static func hashes(_ files: [String: String]) -> [String: String] {
    files.mapValues { NativeCodex.digest(Data($0.utf8)) }
  }
  static func freezeID(_ files: [String: String]) throws -> String {
    NativeCodex.digest(try bytes(hashes(files)))
  }

  static func openFolder(_ folder: CodexDirectory) throws -> Int32 {
    let fd = open(folder.path, O_DIRECTORY | O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    guard fd >= 0 else { throw TeamError.changedDirectory }
    var info = stat()
    guard fstat(fd, &info) == 0, UInt64(info.st_dev) == folder.device,
      UInt64(info.st_ino) == folder.inode
    else {
      close(fd)
      throw TeamError.changedDirectory
    }
    return fd
  }
  static func taskDirectory(parent: CodexDirectory, role: String, operation: String) throws
    -> CodexDirectory
  {
    guard TeamMember.roles.contains(role), UUID(uuidString: operation) != nil else {
      throw TeamError.invalidInput
    }
    let fd = try openFolder(parent)
    defer { close(fd) }
    let name = role + "-" + operation
    guard mkdirat(fd, name, 0o700) == 0 else { throw TeamError.storage }
    var child = stat()
    guard fstatat(fd, name, &child, AT_SYMLINK_NOFOLLOW) == 0, child.st_mode & S_IFMT == S_IFDIR
    else { throw TeamError.changedDirectory }
    return CodexDirectory(
      path: parent.path + "/" + name, device: UInt64(child.st_dev), inode: UInt64(child.st_ino),
      isolated: true)
  }

  static func workFolder(for run: TeamRun) throws -> CodexDirectory {
    guard run.hasPrivateWorkspace else { return run.folder }
    guard UUID(uuidString: run.id) != nil else { throw TeamError.invalidInput }
    let fd = try openFolder(run.folder)
    defer { close(fd) }
    let leaf = ".twos-work-" + run.id
    guard mkdirat(fd, leaf, 0o700) == 0 || errno == EEXIST else { throw TeamError.storage }
    var info = stat()
    guard fstatat(fd, leaf, &info, AT_SYMLINK_NOFOLLOW) == 0,
      info.st_mode & S_IFMT == S_IFDIR, info.st_uid == getuid(), info.st_mode & 0o077 == 0
    else {
      throw TeamError.changedDirectory
    }
    return CodexDirectory(
      path: run.folder.path + "/" + leaf, device: UInt64(info.st_dev),
      inode: UInt64(info.st_ino), isolated: true)
  }

  // Only the Owner decision changes after the four files have been published.
  static func updateDecision(
    in folder: CodexDirectory, leaf: String, previous: String, next: String
  ) throws {
    guard !leaf.isEmpty, !leaf.contains("/"), leaf != ".", leaf != ".." else {
      throw TeamError.changedDirectory
    }
    let parent = try openFolder(folder)
    defer { close(parent) }
    let dir = openat(parent, leaf, O_DIRECTORY | O_RDONLY | O_NOFOLLOW | O_CLOEXEC)
    guard dir >= 0 else { throw TeamError.changedDirectory }
    defer { close(dir) }
    let old = openat(dir, "delivery.json", O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
    guard old >= 0 else { throw TeamError.wrongVersion }
    let original = FileHandle(fileDescriptor: old, closeOnDealloc: true)
    defer { try? original.close() }
    var info = stat()
    guard fstat(old, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_size <= 6_291_456,
      let bytes = try original.readToEnd(), bytes == Data(previous.utf8) || bytes == Data(next.utf8)
    else { throw TeamError.wrongVersion }
    if bytes == Data(next.utf8) { return }
    let tmp = ".decision-" + UUID().uuidString
    let fd = openat(dir, tmp, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
    guard fd >= 0 else { throw TeamError.storage }
    defer { _ = unlinkat(dir, tmp, 0) }
    let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
    try handle.write(contentsOf: Data(next.utf8))
    try handle.synchronize()
    try handle.close()
    var current = stat()
    guard fstatat(dir, "delivery.json", &current, AT_SYMLINK_NOFOLLOW) == 0,
      current.st_ino == info.st_ino, current.st_dev == info.st_dev,
      renameat(dir, tmp, dir, "delivery.json") == 0
    else { throw TeamError.wrongVersion }
  }

  // The selected directory is re-bound by inode. Publish all four files together.
  static func export(_ files: [String: String], to folder: CodexDirectory, name: String) throws {
    let frozen = name.hasSuffix("-frozen")
    let expected: Set<String> =
      frozen
      ? ["dashboard.html", "summary.md"]
      : ["dashboard.html", "summary.md", "review.md", "delivery.json"]
    guard Set(files.keys) == expected,
      files.values.reduce(0, { $0 + $1.utf8.count }) <= 6 * 1024 * 1024,
      name == "Delivery" || (name.hasPrefix("Delivery-") && UUID(uuidString: String(name.dropFirst(9)))?.uuidString == String(name.dropFirst(9)))
        || name.range(
          of: #"^TWOS-[A-Fa-f0-9-]{36}-v[1-3]-(frozen|reviewed|accepted|changes)$"#,
          options: .regularExpression) != nil
    else { throw TeamError.invalidReport }
    let parent = try openFolder(folder)
    defer { close(parent) }
    let stage = ".twos-" + UUID().uuidString
    guard mkdirat(parent, stage, 0o700) == 0 else { throw TeamError.storage }
    let dir = openat(parent, stage, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
    guard dir >= 0 else {
      _ = unlinkat(parent, stage, AT_REMOVEDIR)
      throw TeamError.storage
    }
    var published = false
    defer {
      if !published {
        for f in files.keys { _ = unlinkat(dir, f, 0) }
        _ = unlinkat(parent, stage, AT_REMOVEDIR)
      }
      close(dir)
    }
    for (name, body) in files {
      let fd = openat(dir, name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o600)
      guard fd >= 0 else { throw TeamError.storage }
      let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
      try handle.write(contentsOf: Data(body.utf8))
      try handle.synchronize()
      try handle.close()
    }
    guard renameatx_np(parent, stage, parent, name, UInt32(RENAME_EXCL)) == 0 else {
      if errno == EEXIST { throw TeamError.alreadyExported }
      throw TeamError.storage
    }
    published = true
  }
}
