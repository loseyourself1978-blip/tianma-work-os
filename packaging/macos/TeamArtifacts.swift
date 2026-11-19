import Darwin
import Foundation

struct TeamWriteIntent: Codable {
  let path: String, temp: String, file: TeamOwnedFile
  let previous: TeamOwnedFile?
}
enum TeamArtifacts {
  static func components(_ path: String) throws -> [String] {
    let parts = path.split(separator: "/", omittingEmptySubsequences: false).map(String.init)
    guard !parts.isEmpty, path.utf8.count < 1024,
      parts.allSatisfy({ s in
        !s.isEmpty && s.utf8.count <= 255 && !s.hasPrefix(".") && !s.contains("\\")
          && !s.contains(":")
          && !s.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains)
      })
    else { throw TeamError.invalidReport }
    return parts
  }
  static func validate(_ files: [String: String]) throws {
    var keys = Set<String>()
    for n in files.keys {
      _ = try components(n)
      let k = n.precomposedStringWithCanonicalMapping.lowercased()
      guard keys.insert(k).inserted else { throw TeamError.fileConflict }
    }
    for k in keys {
      let parts = k.split(separator: "/")
      for i in 1..<parts.count where keys.contains(parts.prefix(i).joined(separator: "/")) {
        throw TeamError.fileConflict
      }
    }
  }
  static func containingFolder(_ folder: CodexDirectory, _ path: String, create: Bool) throws -> (
    Int32, String
  ) {
    let parts = try components(path)
    var fd = try TeamFiles.openFolder(folder)
    do {
      for name in parts.dropLast() {
        if create && mkdirat(fd, name, 0o755) != 0 && errno != EEXIST {
          throw TeamError.changedDirectory
        }
        let child = openat(fd, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard child >= 0 else { throw TeamError.changedDirectory }
        close(fd)
        fd = child
      }
      return (fd, parts.last!)
    } catch {
      close(fd)
      throw error
    }
  }
  private static func inspected(_ dir: Int32, _ name: String) throws -> (TeamOwnedFile, Data)? {
    let fd = openat(dir, name, O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC)
    if fd < 0 && errno == ENOENT { return nil }
    guard fd >= 0 else { throw TeamError.fileConflict }
    let h = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
    defer { try? h.close() }
    var info = stat()
    guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_size <= 8 * 1024 * 1024,
      let data = try h.read(upToCount: 8 * 1024 * 1024 + 1) ?? (info.st_size == 0 ? Data() : nil),
      data.count == info.st_size
    else { throw TeamError.fileConflict }
    return (
      TeamOwnedFile(
        hash: NativeCodex.digest(data), device: UInt64(info.st_dev), inode: UInt64(info.st_ino)),
      data
    )
  }
  static func identity(_ dir: Int32, _ name: String) throws -> TeamOwnedFile? {
    try inspected(dir, name)?.0
  }
  static func verifiedContents(_ path: String, owner: TeamOwnedFile, in folder: CodexDirectory)
    throws -> Data
  {
    let (fd, name) = try containingFolder(folder, path, create: false)
    defer { close(fd) }
    guard let (current, bytes) = try inspected(fd, name), current == owner else {
      throw TeamError.fileConflict
    }
    return bytes
  }
  static func stage(
    _ text: String, path: String, in folder: CodexDirectory, previous: TeamOwnedFile?
  ) throws -> TeamWriteIntent {
    let (dir, name) = try containingFolder(folder, path, create: true)
    defer { close(dir) }
    guard try identity(dir, name) == previous else { throw TeamError.fileConflict }
    let tmp = ".twos-write-" + UUID().uuidString
    let fd = openat(dir, tmp, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0o644)
    guard fd >= 0 else { throw TeamError.storage }
    let h = FileHandle(fileDescriptor: fd, closeOnDealloc: true)
    do {
      try h.write(contentsOf: Data(text.utf8))
      try h.synchronize()
      try h.close()
      guard let file = try identity(dir, tmp) else { throw TeamError.storage }
      return TeamWriteIntent(path: path, temp: tmp, file: file, previous: previous)
    } catch {
      try? h.close()
      unlinkat(dir, tmp, 0)
      throw error
    }
  }
  // The intent is durable before publication. An interrupted swap can be
  // recognized by both inode and hash, without adopting another task's file.
  static func commit(_ intent: TeamWriteIntent, in folder: CodexDirectory) throws {
    guard intent.temp.hasPrefix(".twos-write-"),
      UUID(uuidString: String(intent.temp.dropFirst(12))) != nil
    else { throw TeamError.wrongVersion }
    let (dir, name) = try containingFolder(folder, intent.path, create: false)
    defer { close(dir) }
    let current = try identity(dir, name)
    let staged = try identity(dir, intent.temp)
    if current == intent.file {
      if let staged {
        guard staged == intent.previous else { throw TeamError.fileConflict }
        guard unlinkat(dir, intent.temp, 0) == 0 else { throw TeamError.storage }
      }
      return
    }
    guard current == intent.previous, staged == intent.file else { throw TeamError.fileConflict }
    let flag = UInt32(current == nil ? RENAME_EXCL : RENAME_SWAP)
    guard renameatx_np(dir, intent.temp, dir, name, flag) == 0 else { throw TeamError.fileConflict }
    if current != nil {
      guard try identity(dir, intent.temp) == current else {
        // A non-cooperating writer replaced the file between validation and
        // exchange. Never unlink its bytes. Restore only our own published inode.
        if try identity(dir, name) == intent.file {
          _ = renameatx_np(dir, intent.temp, dir, name, UInt32(RENAME_SWAP))
        }
        throw TeamError.fileConflict
      }
      guard unlinkat(dir, intent.temp, 0) == 0 else { throw TeamError.storage }
    }
    _ = fsync(dir)
  }
  static func visible(_ path: String, owner: TeamOwnedFile, in folder: CodexDirectory) throws -> URL
  {
    let (fd, n) = try containingFolder(folder, path, create: false)
    defer { close(fd) }
    guard try identity(fd, n) == owner else { throw TeamError.fileConflict }
    return URL(fileURLWithPath: folder.path).appendingPathComponent(path)
  }
}
