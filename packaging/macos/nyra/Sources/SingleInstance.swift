import AppKit
import Security
import Darwin

enum CompanionIdentity {
    static let bundleIDs = ["com.tianma.nyra","com.tianma.workos.nyra","local.nyra.companion.preview"]
    static func compatible(_ app: NSRunningApplication) -> Bool {
        guard let url = app.bundleURL, let bundle = Bundle(url:url),
              bundleIDs.contains(bundle.bundleIdentifier ?? ""),
              bundle.object(forInfoDictionaryKey:"NyraVisibilityProtocol") as? Int == 1 else { return false }
        var code: SecStaticCode?; var requirement: SecRequirement?
        let text = "anchor apple generic and certificate leaf[subject.OU] = BZJWQJ352K"
        guard SecStaticCodeCreateWithPath(url as CFURL,[],&code) == errSecSuccess,
              SecRequirementCreateWithString(text as CFString,[],&requirement) == errSecSuccess,
              let code = code, let requirement = requirement else { return false }
        return SecStaticCodeCheckValidity(code,SecCSFlags(rawValue:kSecCSStrictValidate),requirement) == errSecSuccess
    }
}

extension Companion {
    // A shared production lock covers both distribution forms. Engineering
    // instances opt into isolated prefs and locks; they never claim production.
    func acquireSingleInstance() -> Bool {
        if !isolated {
            let others = NSWorkspace.shared.runningApplications.filter {
                $0.processIdentifier != ProcessInfo.processInfo.processIdentifier && !$0.isTerminated &&
                CompanionIdentity.bundleIDs.contains($0.bundleIdentifier ?? "")
            }
            if let other = others.first {
                if others.count == 1, CompanionIdentity.compatible(other), let url = other.bundleURL {
                    let options = NSWorkspace.OpenConfiguration(); options.activates = false
                    let action = launchVisibility == false ? "hide" : "show"
                    NSWorkspace.shared.open([URL(string:"nyra://visibility/"+action)!],withApplicationAt:url,configuration:options) { _, _ in
                        DispatchQueue.main.async { NSApp.terminate(nil) }
                    }
                } else {
                    let alert = NSAlert(); alert.messageText = "另一版本的夜璃正在运行 / Another Nyra version is running"
                    alert.informativeText = "请从原夜璃菜单正常退出后再打开此版本。不会停止 TWOS 任务。 / Quit the existing Nyra from its menu before opening this version. TWOS work continues."
                    alert.runModal(); NSApp.terminate(nil)
                }
                return false
            }
        }
        let root = isolated ? stateDirectory : FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("Nyra",isDirectory:true)
        do { try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true) } catch { NSApp.terminate(nil); return false }
        lockFD = Darwin.open(root.appendingPathComponent("instance-v1.lock").path,O_CREAT | O_RDWR | O_NOFOLLOW,0o600)
        var st = stat()
        guard lockFD >= 0, fstat(lockFD,&st) == 0, st.st_uid == getuid(), st.st_mode & S_IFMT == S_IFREG,
              flock(lockFD,LOCK_EX | LOCK_NB) == 0 else {
            if lockFD >= 0 { close(lockFD); lockFD = -1 }
            // Another launch won the race. Do not create a second window.
            NSApp.terminate(nil); return false
        }
        return true
    }
}
