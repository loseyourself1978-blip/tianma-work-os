import AppKit
import Foundation

// Shared 1.0 adapter. Only the nested helper auto-selects its signed parent;
// standalone Nyra keeps explicit read-only endpoint selection.
extension Companion {
    static func bundledStatusSelection(helper: URL, stateDirectory: URL) throws -> BridgeSelection {
        let helper = helper.standardizedFileURL
        let parent = helper.deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        guard Bundle(url:helper)?.bundleIdentifier == "com.tianma.workos.nyra",
              helper == parent.appendingPathComponent("Contents/Helpers/TWOS Nyra.app"),
              helper.resolvingSymlinksInPath() == helper,
              let producer = Bundle(url:parent), let id = producer.bundleIdentifier,
              id == "com.tianma.workos", stateDirectory.lastPathComponent == "nyra" else { throw BridgeError.wrongPeer }
        let endpoint = stateDirectory.deletingLastPathComponent().appendingPathComponent("nyra-status/endpoint.json")
        _ = try NyraStatusClient.readEndpoint(endpoint.path)
        return BridgeSelection(endpoint:endpoint.path,producerApp:parent.path,producerBundleID:id,
                               producerCodeHash:try NyraStatusClient.codeHash(parent))
    }

    // Visibility only; URLs cannot supply task states, execute code or select
    // an arbitrary endpoint. Repeated show/hide is idempotent.
    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls where ["twos-nyra","nyra"].contains(url.scheme ?? "") && url.host == "visibility" && url.query == nil && url.fragment == nil {
            guard panel != nil else {
                if url.path == "/show" { launchVisibility = true }
                else if url.path == "/hide" { launchVisibility = false }
                continue
            }
            if url.path == "/show" { if !panel.isVisible && stage?.isVisible != true { showPanel() } }
            else if url.path == "/hide" { if panel.isVisible || stage?.isVisible == true { hideAll() } }
            else if url.path != "/status" { continue }
            publishVisibility()
        }
    }

    func publishVisibility(persistPreference: Bool = true, heartbeat: Bool = false) {
        guard panel != nil else { return }
        let visible = panel.isVisible || stage?.isVisible == true
        let connected = liveReducer.connected && reactive.connected && !reactive.simulation
        var state: [String: Any] = ["visible":visible,"pending":false,
            "pid":ProcessInfo.processInfo.processIdentifier,"bundle":Bundle.main.bundleURL.path,
            "runtime":"Nyra 1.0","runBinding":connected ? "CONNECTED_READONLY" : "NOT_CONNECTED"]
        if connected, let event = liveReducer.current {
            state["producerInstance"] = event.producer_instance_id
            state["sessionID"] = event.session_id; state["taskID"] = event.task_id ?? ""
            state["taskState"] = event.state.rawValue
            state["activitySide"] = event.activity_side ?? "unknown"
        }
        // Current consumer rendering facts, never requested/planned animation.
        state["consumerInstance"]=consumerInstance
        state["animation"]=animationName;state["frameAsset"]=frameCursor?.assetID ?? ""
        state["frameCount"]=displayedFrames[activeSetKey+":"+animationName,default:0]
        state["frameTimer"]=frameTimer?.isValid == true
        state["reduceMotion"]=NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        state["lastSnapshotUptime"]=liveReducer.lastReceipt
        state["lastStateChangeAt"]=liveReducer.current?.timestamp ?? ""
        if let observations=liveReducer.current?.pane_observations,let data=try? JSONEncoder().encode(observations),let array=try? JSONSerialization.jsonObject(with:data) {state["paneObservations"]=array}
        // Duplicate snapshots are heartbeats, not state transitions. Avoid
        // rewriting preference files or posting UI events every two seconds.
        let changed = !NSDictionary(dictionary:state).isEqual(to:lastPublishedVisibility)
        if !changed && !heartbeat { return }
        lastPublishedVisibility = state
        state["heartbeatUptime"] = ProcessInfo.processInfo.systemUptime
        state["updatedAt"] = Date().timeIntervalSince1970
        let output = stateDirectory.appendingPathComponent("visibility-state.json")
        if let bytes = try? JSONSerialization.data(withJSONObject:state) {
            try? bytes.write(to:output,options:.atomic)
            try? FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:output.path)
        }
        let preference = preferenceDirectory.appendingPathComponent("visibility-preference.json")
        if persistPreference && changed, let bytes = try? JSONSerialization.data(withJSONObject:["visible":visible]) {
            try? bytes.write(to:preference,options:.atomic)
            try? FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:preference.path)
        }
        if changed && !heartbeat {DistributedNotificationCenter.default().postNotificationName(Notification.Name("com.tianma.nyra.visibility"),object:Bundle.main.bundleIdentifier,userInfo:nil,deliverImmediately:true)}
    }
}
