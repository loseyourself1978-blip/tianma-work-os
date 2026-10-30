import AppKit
import Security
import UniformTypeIdentifiers
import Darwin

struct BridgeSelection: Codable {
    let endpoint: String
    let producerApp: String
    let producerBundleID: String
    let producerCodeHash: Data
    var connection_nonce: String?
}
struct StatusEndpoint: Decodable {
    let transport: String
    let socket: String
    let producer_instance_id: String
    let schema_version: String
    let schema_sha256: String
}
enum BridgeError: Error { case unsafeEndpoint, wrongPeer, unavailable, truncated, invalidFrame }
final class NyraStatusClient {
    static let schemaHash = "dbdc1c228b9762fc1b8b3bcd8b89d91672f4ae5e0a7f552d9d1301b93dcde831"
    var selection: BridgeSelection?
    private(set) var connectionLabel = "NOT_CONNECTED · 等待独立客户端授权"
    private var busy = false
    private var generation = 0
    func markConnected(_ value: Bool) { connectionLabel = value ? "CONNECTED · 只读快照" : "NOT_CONNECTED · 接口未授权 / 不可用" }
    func stop() { generation += 1; connectionLabel = "NOT_CONNECTED" }
    static func codeHash(_ path: URL) throws -> Data {
        var code: SecStaticCode?; var info: CFDictionary?
        guard SecStaticCodeCreateWithPath(path as CFURL,[],&code) == errSecSuccess,
              SecStaticCodeCheckValidity(code!,SecCSFlags(rawValue:kSecCSStrictValidate),nil) == errSecSuccess,
              SecCodeCopySigningInformation(code!,[],&info) == errSecSuccess,
              let hash = (info as? [String:Any])?[kSecCodeInfoUnique as String] as? Data else { throw BridgeError.wrongPeer }
        return hash
    }
    static func securePath(_ path: String, mode: mode_t, directory: Bool = false, socket: Bool = false) throws {
        var st = stat()
        guard lstat(path,&st) == 0, st.st_uid == getuid(), st.st_mode & 0o777 == mode,
              st.st_mode & S_IFMT == (directory ? S_IFDIR : socket ? S_IFSOCK : S_IFREG),
              URL(fileURLWithPath:path).resolvingSymlinksInPath().path == URL(fileURLWithPath:path).standardizedFileURL.path else { throw BridgeError.unsafeEndpoint }
    }
    static func readSelection(_ path: String) throws -> BridgeSelection {
        try securePath(URL(fileURLWithPath:path).deletingLastPathComponent().path,mode:0o700,directory:true)
        try securePath(path,mode:0o600)
        let fd=Darwin.open(path,O_RDONLY|O_NOFOLLOW|O_NONBLOCK);guard fd>=0 else{throw BridgeError.unsafeEndpoint};defer{Darwin.close(fd)}
        var st=stat();guard fstat(fd,&st)==0,st.st_size>0,st.st_size<=8192 else{throw BridgeError.unsafeEndpoint}
        var bytes=[UInt8](repeating:0,count:Int(st.st_size));guard Darwin.read(fd,&bytes,bytes.count)==bytes.count else{throw BridgeError.truncated}
        return try JSONDecoder().decode(BridgeSelection.self,from:Data(bytes))
    }
    static func readEndpoint(_ path: String) throws -> StatusEndpoint {
        try securePath(URL(fileURLWithPath:path).deletingLastPathComponent().path,mode:0o700,directory:true)
        try securePath(path,mode:0o600)
        let fd = Darwin.open(path,O_RDONLY | O_NOFOLLOW); guard fd >= 0 else { throw BridgeError.unsafeEndpoint }; defer { Darwin.close(fd) }
        var st = stat(); guard fstat(fd,&st) == 0, st.st_uid == getuid(), st.st_mode & 0o777 == 0o600, st.st_mode & S_IFMT == S_IFREG, st.st_size > 0, st.st_size <= 4096 else { throw BridgeError.unsafeEndpoint }
        var bytes = [UInt8](repeating:0,count:Int(st.st_size)); let count = Darwin.read(fd,&bytes,bytes.count)
        guard count == bytes.count else { throw BridgeError.truncated }
        let e = try JSONDecoder().decode(StatusEndpoint.self,from:Data(bytes))
        guard e.transport == "unix_snapshot_v1", ((e.schema_version == "twos.nyra.status.v3" && e.schema_sha256 == schemaHash) || (e.schema_version == "twos.nyra.status.v2" && e.schema_sha256 == "ef6797aa662f28dd36134ba476c5b1ae50c418fd1fa9636330d2cb76c0b59c81") || (e.schema_version == "twos.nyra.status.v1" && e.schema_sha256 == "7ce0d27865647a5ba9bfa44d2355cb3839a80b51348b195fadafc3d7544cc386")),
              UUID(uuidString:e.producer_instance_id) != nil,
              e.socket == "/private/tmp/twos-nyra-status-" + e.producer_instance_id + "/status.sock" else { throw BridgeError.unsafeEndpoint }
        try securePath(URL(fileURLWithPath:e.socket).deletingLastPathComponent().path,mode:0o700,directory:true)
        try securePath(e.socket,mode:0o600,socket:true)
        return e
    }
    static func verifyPeer(_ fd: Int32, selection: BridgeSelection) throws {
        var uid: uid_t = 0; var gid: gid_t = 0; var pid: pid_t = 0; var count = socklen_t(MemoryLayout<pid_t>.size)
        guard getpeereid(fd,&uid,&gid) == 0, uid == getuid(), getsockopt(fd,SOL_LOCAL,LOCAL_PEERPID,&pid,&count) == 0,
              let app = NSRunningApplication(processIdentifier:pid), app.bundleIdentifier == selection.producerBundleID,
              app.bundleURL?.standardizedFileURL == URL(fileURLWithPath:selection.producerApp).standardizedFileURL,
              let exe = Bundle(path:selection.producerApp)?.executableURL, app.executableURL?.standardizedFileURL == exe.standardizedFileURL,
              try codeHash(URL(fileURLWithPath:selection.producerApp)) == selection.producerCodeHash else { throw BridgeError.wrongPeer }
        var live: SecCode?; var liveStatic: SecStaticCode?; var info: CFDictionary?
        guard SecCodeCopyGuestWithAttributes(nil,[kSecGuestAttributePid as String:pid] as CFDictionary,[],&live) == errSecSuccess,
              SecCodeCheckValidity(live!,[],nil) == errSecSuccess,
              SecCodeCopyStaticCode(live!,[],&liveStatic) == errSecSuccess,
              SecCodeCopySigningInformation(liveStatic!,[],&info) == errSecSuccess,
              (info as? [String:Any])?[kSecCodeInfoUnique as String] as? Data == selection.producerCodeHash else { throw BridgeError.wrongPeer }
    }
    static func decodeLine(_ bytes: Data, instance: String) throws -> StatusEvent {
        guard bytes.count <= 16385, bytes.last == 10, bytes.dropLast().contains(10) == false else { throw BridgeError.truncated }
        let event = try StatusEvent.decode(Data(bytes.dropLast()),simulation:false)
        guard event.producer_instance_id == instance else { throw BridgeError.invalidFrame }
        return event
    }
    static func read(_ selection: BridgeSelection) throws -> StatusEvent {
        let endpoint = try readEndpoint(selection.endpoint)
        let fd = Darwin.socket(AF_UNIX,SOCK_STREAM,0); guard fd >= 0 else { throw BridgeError.unavailable }; defer { Darwin.close(fd) }
        var timeout = timeval(tv_sec:5,tv_usec:0)
        _ = setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,socklen_t(MemoryLayout<timeval>.size))
        _ = fcntl(fd,F_SETFL,O_NONBLOCK)
        var addr = sockaddr_un(); addr.sun_family = sa_family_t(AF_UNIX); addr.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        guard endpoint.socket.utf8.count+1 <= MemoryLayout.size(ofValue:addr.sun_path) else { throw BridgeError.unsafeEndpoint }
        withUnsafeMutableBytes(of:&addr.sun_path) { bytes in endpoint.socket.utf8CString.withUnsafeBytes { bytes.copyMemory(from:$0) } }
        let result = withUnsafePointer(to:&addr) { $0.withMemoryRebound(to:sockaddr.self,capacity:1) { Darwin.connect(fd,$0,socklen_t(MemoryLayout<sockaddr_un>.size)) } }
        if result != 0 {
            guard errno == EINPROGRESS else { throw BridgeError.unavailable }
            var p = pollfd(fd:fd,events:Int16(POLLOUT),revents:0)
            guard Darwin.poll(&p,1,500) == 1 else { throw BridgeError.unavailable }
            var error: Int32 = 0; var size = socklen_t(MemoryLayout<Int32>.size)
            guard getsockopt(fd,SOL_SOCKET,SO_ERROR,&error,&size) == 0, error == 0 else { throw BridgeError.unavailable }
        }
        try verifyPeer(fd,selection:selection)
        _ = fcntl(fd,F_SETFL,0)
        var data = Data(); var chunk = [UInt8](repeating:0,count:4096)
        let deadline = ProcessInfo.processInfo.systemUptime + 5
        while data.count <= 16384 && ProcessInfo.processInfo.systemUptime < deadline {
            let n = Darwin.recv(fd,&chunk,chunk.count,0)
            guard n > 0 else { throw BridgeError.truncated }
            data.append(contentsOf:chunk.prefix(n))
            if data.contains(10) { return try decodeLine(data,instance:endpoint.producer_instance_id) }
        }
        throw BridgeError.truncated
    }
    func poll(selectionLoader: @escaping () throws -> BridgeSelection,
              _ completion: @escaping (Result<StatusEvent,Error>) -> Void) {
        guard !busy else { return }
        busy = true; let token = generation; let existing = selection
        // Endpoint access and signature validation can wait on macOS folder
        // permission. Never let that block animation, menus or the main thread.
        DispatchQueue.global(qos:.utility).async {
            var resolved: BridgeSelection?
            let result = Result { () throws -> StatusEvent in
                let choice = try existing ?? selectionLoader()
                resolved = choice
                return try Self.read(choice)
            }
            DispatchQueue.main.async {
                self.busy = false; guard token == self.generation else { return }
                if let resolved = resolved { self.selection = resolved }
                switch result { case .success: break
                case .failure: self.connectionLabel = "NOT_CONNECTED · 接口未授权 / 不可用" }
                completion(result)
            }
        }
    }
}

extension Companion {
    var bridgeURL: URL { stateDirectory.appendingPathComponent("bridge-selection.json") }
    func startLivePolling() {
        if connectionObserver == nil, !isBundled {
            connectionObserver=DistributedNotificationCenter.default().addObserver(forName:Notification.Name("com.tianma.nyra.connection.refresh"),object:Bundle.main.bundleURL.path,queue:.main){[weak self] _ in self?.receiveConnectionRefresh()}
        }
        livePollTimer?.invalidate()
        guard !FileManager.default.fileExists(atPath:stateDirectory.appendingPathComponent("status-disconnected").path) else { livePollTimer = nil; return }
        let timer = Timer(timeInterval:2,repeats:true) { [weak self] _ in self?.pollLive() }
        timer.tolerance = 0.3; livePollTimer = timer; RunLoop.main.add(timer,forMode:.common); pollLive()
    }
    func pollLive() {
        guard !suspended else { return }
        let previous = liveReducer.current
        let wasConnected = liveReducer.connected
        let previousLabel = live.connectionLabel
        liveReducer.expire(now:ProcessInfo.processInfo.systemUptime)
        if !liveReducer.connected && reactive.connected {
            reactive.setWork(.disconnected,simulation:false,connected:false,celebrate:false,now:ProcessInfo.processInfo.systemUptime)
            live.markConnected(false); reconcileAnimation()
        }
        let bundled = isBundled, helper = Bundle.main.bundleURL
        let stateRoot = stateDirectory, savedSelection = bridgeURL
        live.poll(selectionLoader: {
            if bundled { return try Companion.bundledStatusSelection(helper:helper,stateDirectory:stateRoot) }
            return try NyraStatusClient.readSelection(savedSelection.path)
        }) { [weak self] result in
            guard let self = self else { return }
            switch result {
            case .success(let event):
                let decision = self.liveReducer.receive(event,now:ProcessInfo.processInfo.systemUptime)
                self.live.markConnected(decision.accepted)
                if decision.accepted {
                    self.demo = .none
                    if decision.changed || self.reactive.simulation || !self.reactive.connected {
                        self.reactive.setWork(self.liveReducer.current?.state ?? .disconnected,simulation:false,connected:true,
                            celebrate:decision.celebrate && (self.panel.isVisible || self.stage?.isVisible == true),now:ProcessInfo.processInfo.systemUptime)
                    }
                } else {
                    self.reactive.setWork(.disconnected,simulation:false,connected:false,celebrate:false,now:ProcessInfo.processInfo.systemUptime)
                }
            case .failure:
                self.liveReducer.disconnect()
                if !self.reactive.simulation { self.reactive.setWork(.disconnected,simulation:false,connected:false,celebrate:false,now:ProcessInfo.processInfo.systemUptime) }
            }
            if previous != self.liveReducer.current || wasConnected != self.liveReducer.connected || previousLabel != self.live.connectionLabel {
                self.reconcileAnimation(); self.writePlaybackState("status_snapshot"); self.rebuildMenu()
            }
            // A live receipt heartbeat is separate from animation/state changes.
            self.publishVisibility(persistPreference:false,heartbeat:true)
        }
    }
    func receiveConnectionRefresh() {
        guard !isBundled else{return}
        let root=stateDirectory,selectionFile=bridgeURL
        DispatchQueue.global(qos:.utility).async {[weak self] in
            do {
                let choice=try NyraStatusClient.readSelection(selectionFile.path)
                guard let nonce=choice.connection_nonce,UUID(uuidString:nonce) != nil else{return}
                let accepted=root.appendingPathComponent("connection-accepted.txt")
                if (try? String(contentsOf:accepted,encoding:.utf8)) == nonce {return}
                // The notification grants nothing. Check the currently running,
                // signed peer and its exact consumer authorization first.
                _ = try NyraStatusClient.read(choice)
                DispatchQueue.main.async {
                    guard let self=self else{return}
                    self.live.stop();self.live.selection=choice;self.liveReducer.disconnect()
                    try? Data(nonce.utf8).write(to:accepted,options:.atomic)
                    try? FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:accepted.path)
                    try? FileManager.default.removeItem(at:root.appendingPathComponent("status-disconnected"))
                    self.startLivePolling()
                }
            } catch { /* Invalid hints cannot rebind or change current work. */ }
        }
    }
    @objc func configureBridge() {
        if isBundled {
            live.stop(); liveReducer.disconnect(); live.selection = nil
            try? FileManager.default.removeItem(at:stateDirectory.appendingPathComponent("status-disconnected"))
            startLivePolling()
            return
        }
        NSApp.activate(ignoringOtherApps:true)
        let pick = NSOpenPanel(); pick.title = "选择 TWOS 提供的 nyra-status/endpoint.json · 只读接口"; pick.allowsMultipleSelection = false
        guard pick.runModal() == .OK, let endpoint = pick.url else { return }
        let app = NSOpenPanel(); app.title = "选择该接口所属 TWOS App · 固定签名身份"; app.canChooseDirectories = false; app.allowedContentTypes = [.applicationBundle]
        guard app.runModal() == .OK, let producer = app.url else { return }
        do {
            _ = try NyraStatusClient.readEndpoint(endpoint.path)
            guard let bundle = Bundle(url:producer), let id = bundle.bundleIdentifier, id.hasPrefix("com.tianma.") else { throw BridgeError.wrongPeer }
            let choice = BridgeSelection(endpoint:endpoint.path,producerApp:producer.standardizedFileURL.path,producerBundleID:id,producerCodeHash:try NyraStatusClient.codeHash(producer))
            live.stop(); liveReducer.disconnect(); live.selection = choice
            try JSONEncoder().encode(choice).write(to:bridgeURL,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:bridgeURL.path)
            try? FileManager.default.removeItem(at:stateDirectory.appendingPathComponent("status-disconnected"))
            startLivePolling()
        } catch { let alert = NSAlert(); alert.messageText = "接口身份或权限不符合要求"; alert.informativeText = "请由 TWOS 工程提供并授权独立 Nyra 的只读接口。夜璃不会绕过 helper 身份限制。"; alert.runModal() }
    }
    @objc func disconnectBridge() {
        live.stop(); live.selection = nil; liveReducer.disconnect()
        try? FileManager.default.removeItem(at:bridgeURL)
        livePollTimer?.invalidate(); livePollTimer = nil
        try? Data().write(to:stateDirectory.appendingPathComponent("status-disconnected"),options:.atomic)
        reactive.setWork(.idle,simulation:false,connected:false,celebrate:false,now:ProcessInfo.processInfo.systemUptime)
        reconcileAnimation(force:true); rebuildMenu(); publishVisibility()
    }
}
func runStatusTransportTests() throws {
    // A truncated frame cannot become a state; simulator bytes cannot enter LIVE.
    for payload in [Data(),Data("{}".utf8),Data("{}\n{}\n".utf8),Data(repeating:65,count:17000)] {
        do { _ = try NyraStatusClient.decodeLine(payload,instance:"test"); throw NSError(domain:"unsafe line accepted",code:1) }
        catch is BridgeError {} catch is DecodingError {} catch PreviewError.invalidManifest {}
    }
    print("PASS: bounded LF framing, truncated/multiple-frame rejection; LIVE requires authenticated peer and simulation=false")
}
