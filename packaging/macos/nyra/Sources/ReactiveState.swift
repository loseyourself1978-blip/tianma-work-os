import Foundation
import CoreGraphics

enum PointerDirection {
    // Existing look_around order: UP, then clockwise in 22.5-degree steps.
    // A small dead zone and angular hysteresis avoid chatter near boundaries.
    static func name(point: CGPoint, character: CGRect, sixteen: Bool, previous: String) -> String {
        let dx = point.x-character.midX, dy = point.y-character.midY
        if hypot(dx,dy) < min(character.width,character.height)*0.06 { return "gaze_center" }
        if !sixteen { return dx < -character.width*0.04 ? "gaze_left" : dx > character.width*0.04 ? "gaze_right" : "gaze_center" }
        let angle = (atan2(dx,dy)+2*Double.pi).truncatingRemainder(dividingBy:2*Double.pi)
        let step = 2*Double.pi/16
        if previous.hasPrefix("gaze_"), let old = Int(previous.dropFirst(5)), (0..<16).contains(old) {
            let delta = abs(atan2(sin(angle-Double(old)*step),cos(angle-Double(old)*step)))
            if delta < step/2 + Double.pi/90 { return previous }
        }
        return String(format:"gaze_%02d",Int((angle/step).rounded()) % 16)
    }
}

// No renderer or pointer event may elevate an unverified completion.
enum WorkState: String, CaseIterable, Codable {
    case idle, queued, running, waiting_user, partial, failed, completed_unverified, verified_success, cancelled, disconnected, activity_unknown
    var animation: String {
        switch self {
        case .queued, .waiting_user: return "waiting"
        case .running: return "working"
        // Terminal truth remains in the label; a finished task is not ongoing work.
        case .partial, .completed_unverified, .failed, .cancelled: return "idle"
        default: return "idle"
        }
    }
    var label: String {
        switch self {
        case .idle: return "空闲 / Idle"
        case .queued: return "已排队 / Queued"
        case .running: return "工作中 / Working"
        case .waiting_user: return "等待你确认 · 夜璃不能批准 / Waiting for you · Nyra cannot approve"
        case .partial: return "部分完成 · 仍有待办 / Partial · work remains"
        case .failed: return "执行失败 / Failed"
        case .completed_unverified: return "执行结束 · 尚未核验 / Ended · unverified"
        case .verified_success: return "核验成功 · 非 Owner 接受 / Verified · not overall Owner acceptance"
        case .cancelled: return "任务已取消 / Cancelled"
        case .activity_unknown: return "活动识别异常 · 通道单独核验 / Activity observation unknown · transport checked separately"
        case .disconnected: return "连接中断 · 状态未知 / Disconnected · unknown"
        }
    }
}

struct PaneObservation: Codable, Equatable {
    let side: String
    let state: WorkState
    let reason: String
    let fresh: Bool
}
struct StatusEvent: Decodable, Equatable {
    let schema_version: String
    let producer_instance_id: String
    let event_id: String
    let sequence: UInt64
    let timestamp: String
    let session_id: String
    let task_id: String?
    let state: WorkState
    let source: String
    let simulation: Bool
    let evidence_ref: String?
    let activity_side: String?
    var pane_observations: [PaneObservation]? = nil
    static func decode(_ data: Data, simulation: Bool) throws -> StatusEvent {
        let required: Set<String> = ["schema_version","producer_instance_id","event_id","sequence","timestamp","session_id","task_id","state","source","simulation"]
        guard data.count <= 16384, let raw = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              required.isSubset(of: Set(raw.keys)), Set(raw.keys).isSubset(of: required.union(["evidence_ref","activity_side","pane_observations"])) else { throw PreviewError.invalidManifest }
        let v = try JSONDecoder().decode(StatusEvent.self, from: data)
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let date = formatter.date(from: v.timestamp) ?? ISO8601DateFormatter().date(from: v.timestamp)
        guard ["twos.nyra.status.v1","twos.nyra.status.v2","twos.nyra.status.v3"].contains(v.schema_version),
              v.activity_side.map({["left","right","both"].contains($0)}) ?? (v.schema_version == "twos.nyra.status.v1"), v.simulation == simulation, date != nil,
              [v.producer_instance_id,v.event_id,v.session_id].allSatisfy({ !$0.isEmpty && $0.count <= 128 }),
              v.task_id.map({ !$0.isEmpty && $0.count <= 128 }) ?? true,
              v.evidence_ref.map({ $0.count <= 128 }) ?? true,
              simulation ? v.source == "engineering_simulator" : ["twos_runtime","codex_adapter","web_handoff_adapter"].contains(v.source),
              v.state != .verified_success || (v.task_id != nil && !(v.evidence_ref ?? "").isEmpty) else { throw PreviewError.invalidManifest }
        if v.schema_version=="twos.nyra.status.v3" {
            guard let panes=v.pane_observations,panes.count==2,Set(panes.map(\.side))==Set(["left","right"]),
                  panes.allSatisfy({$0.reason.range(of:"^[A-Z0-9_]{1,80}$",options:.regularExpression) != nil}),
                  let rawPanes=raw["pane_observations"] as? [[String:Any]],rawPanes.allSatisfy({Set($0.keys)==Set(["side","state","reason","fresh"])}) else{throw PreviewError.invalidManifest}
        } else if v.pane_observations != nil || v.state == .activity_unknown {throw PreviewError.invalidManifest}
        return v
    }
}

struct SnapshotDecision {
    let accepted: Bool
    let changed: Bool
    let celebrate: Bool
}
struct StatusReducer {
    private(set) var current: StatusEvent?
    private(set) var connected = false
    private(set) var lastReceipt: TimeInterval = 0
    private var seen: [String:StatusEvent] = [:]
    private var order: [String] = []
    private(set) var celebrationCount = 0
    mutating func reject() -> SnapshotDecision {
        connected = false
        return SnapshotDecision(accepted:false,changed:false,celebrate:false)
    }
    mutating func receive(_ e: StatusEvent, now: TimeInterval) -> SnapshotDecision {
        let previous = current
        let sameInstance = previous?.producer_instance_id == e.producer_instance_id
        let wasConnected = connected
        if sameInstance, let p = previous {
            if e.sequence < p.sequence { return reject() }
            if e.sequence == p.sequence {
                guard e == p else { return reject() }
                connected = true; lastReceipt = now
                return SnapshotDecision(accepted:true,changed:!wasConnected,celebrate:false)
            }
            if seen[e.event_id] != nil { return reject() }
        }
        let continuous = wasConnected && sameInstance && previous?.session_id == e.session_id && previous?.task_id == e.task_id
            && previous.map { $0.sequence < UInt64.max && e.sequence == $0.sequence + 1 } == true
        let celebrate = continuous && e.state == .verified_success && previous?.state != .verified_success
        if !sameInstance { seen.removeAll(); order.removeAll() }
        // Bounded replay window; sequence never regresses even after an ID ages out.
        if order.count >= 1024 { seen.removeValue(forKey:order.removeFirst()) }
        seen[e.event_id] = e; order.append(e.event_id)
        current = e; connected = true; lastReceipt = now
        if celebrate { celebrationCount += 1 }
        return SnapshotDecision(accepted:true,changed:true,celebrate:celebrate)
    }
    mutating func disconnect() { connected = false }
    mutating func expire(now: TimeInterval) { if now-lastReceipt > 5 { connected = false } }
}

// Pointer entry uses a stable screen-space envelope while an animation changes alpha.
// A stationary pointer cannot repeatedly leave/re-enter a moving silhouette.
struct HoverEdgeTracker {
    private(set) var inside = false
    private var envelope = CGRect.zero
    private var lastPoint: CGPoint?
    mutating func reset() { inside = false; envelope = .zero; lastPoint = nil }
    mutating func observe(point: CGPoint, alphaHit: Bool, character: CGRect) -> String? {
        defer { lastPoint = point }
        if inside {
            if let last = lastPoint, hypot(point.x-last.x,point.y-last.y) < 0.5 { return nil }
            if !envelope.insetBy(dx:-8,dy:-8).contains(point) { inside = false; return "leave" }
        } else if alphaHit {
            inside = true; envelope = character; return "enter"
        }
        return nil
    }
}

struct ReactiveState {
    var work: WorkState = .idle
    var simulation = false
    var connected = false
    var transient: String?
    var transientUntil: TimeInterval = 0
    var dragging = false
    var dragAnimation = "running_right"
    var gaze = "idle"
    var debug: String?
    var debugTrial = false
    var debugUntil: TimeInterval = 0
    var counts: [String: Int] = [:]
    var lastPointer: TimeInterval = -.infinity
    mutating func beginPreview(_ name: String, duration: TimeInterval, now: TimeInterval) {
        debug = name; debugTrial = true; debugUntil = now + min(8,max(1.2,duration))
        // This is a visual override only. Never change work, connection or simulation.
        transient = nil
    }
    mutating func endPreview() { debug = nil; debugTrial = false; debugUntil = 0 }
    mutating func expireVisuals(now: TimeInterval) {
        if debugTrial && now >= debugUntil { endPreview() }
        if transient != nil && now >= transientUntil { transient = nil }
    }
    mutating func input(_ name: String, now: TimeInterval) {
        counts[name, default: 0] += 1
        switch name {
        case "drag_start", "drag_start_left", "drag_start_right":
            if name == "drag_start_left" { dragAnimation = "running_left" }
            if name == "drag_start_right" { dragAnimation = "running_right" }
            dragging = true; endPreview(); transient = nil
        case "drag_left": dragging = true; dragAnimation = "running_left"
        case "drag_right": dragging = true; dragAnimation = "running_right"
        case "release": dragging = false; transient = "settle"; transientUntil = now + 0.65
        case "enter", "click":
            if !debugTrial && now-lastPointer >= 1.5 {
                transient = name == "click" ? "waving" : "jumping"
                transientUntil = now + 1.5; lastPointer = now
            }
        case "leave": gaze = "idle"
        case "gaze_left", "gaze_right", "gaze_center": gaze = name == "gaze_center" ? "idle" : name
        default:
            if name.hasPrefix("gaze_"), let index = Int(name.dropFirst(5)), (0..<16).contains(index) { gaze = name }
        }
    }
    mutating func setWork(_ value: WorkState, simulation: Bool, connected: Bool, celebrate: Bool, now: TimeInterval) {
        work = value; self.simulation = simulation; self.connected = connected
        // A real snapshot updates the base; it cannot cancel a bounded manual preview.
        if celebrate { transient = "verified_success"; transientUntil = now+3 }
        else if transient == "verified_success" && value != .verified_success { transient = nil }
    }
    func selected(now: TimeInterval) -> String {
        if dragging { return dragAnimation }
        if debugTrial, now < debugUntil, let debug = debug { return debug }
        if let transient = transient, now < transientUntil { return transient }
        if (connected || simulation), ![.idle,.disconnected,.verified_success].contains(work) { return work.animation }
        return gaze
    }
    var label: String {
        let base = simulation ? "SIMULATION · " + work.label : connected ? "TWOS · " + work.label : "TWOS NOT_CONNECTED · 本地互动 / Local interaction"
        return debugTrial ? "动作试播 / Manual preview · " + base : base
    }
}

// Pose transitions are rendered artwork, separate from task state and outfit.
struct PoseArbiter {
    enum Phase: String { case standing, reclining, rising, lowering }
    private(set) var phase = Phase.standing
    private var until: TimeInterval = 0
    static let standingActions: Set<String> = ["running_left", "running_right", "jumping"]
    var transitioning: Bool { phase == .rising || phase == .lowering }
    mutating func reset(reclining: Bool) { phase = reclining ? .reclining : .standing; until = 0 }
    mutating func resolve(reclining: Bool, action: String, now: TimeInterval) -> String {
        guard reclining else { reset(reclining:false); return action }
        let needsStanding = Self.standingActions.contains(action)
        switch phase {
        case .reclining:
            if needsStanding { phase = .rising; until = now + 0.32 }
        case .rising:
            if now >= until { phase = .standing }
        case .standing:
            if !needsStanding { phase = .lowering; until = now + 0.32 }
        case .lowering:
            if needsStanding { phase = .rising; until = now + 0.32 }
            else if now >= until { phase = .reclining }
        }
        switch phase {
        case .rising: return "rise"
        case .lowering: return "lower"
        default: return action
        }
    }
}

struct R4Set: Decodable {
    let folder: String
    let neutral: String
    let width: Int
    let height: Int
    let bbox: [Double] // x,y,width,height; AppKit bottom-left origin, UNION across set.
    let sequences: [String: FrameSequence]
    let capabilities: String
    let frame_scales: [String:Double]?
    var rect: CGRect { CGRect(x: bbox[0], y: bbox[1], width: bbox[2], height: bbox[3]) }
    func validated() throws -> R4Set {
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyz0123456789_")
        func safe(_ s: String) -> Bool { !s.isEmpty && s.count < 80 && s.unicodeScalars.allSatisfy { allowed.contains($0) } }
        guard safe(folder), safe(neutral), width > 0, height > 0, bbox.count == 4,
              bbox.allSatisfy(\.isFinite), rect.width > 0, rect.height > 0,
              CGRect(x: 0,y: 0,width: width,height: height).contains(rect), sequences["idle"] != nil else { throw PreviewError.invalidManifest }
        if let scales = frame_scales {
            guard scales.allSatisfy({safe($0.key) && $0.value.isFinite && (0.25...1).contains($0.value)}) else { throw PreviewError.invalidManifest }
        }
        for s in sequences.values {
            guard !s.assetIDs.isEmpty, s.assetIDs.count <= 32, s.assetIDs.count == s.durationsMS.count,
                  s.assetIDs.allSatisfy(safe), s.durationsMS.allSatisfy({ $0 > 0 && $0 <= 10000 }) else { throw PreviewError.invalidManifest }
        }
        return self
    }
    func resolve(_ requested: String) -> (String, FrameSequence) {
        if let exact = sequences[requested] { return (requested,exact) }
        // Missing capability never resolves into a different outfit/pose folder.
        return ("idle",sequences["idle"]!)
    }
}
struct R4Library: Decodable {
    let schemaVersion: Int
    let sets: [String: R4Set]
    func validated() throws -> R4Library {
        let expected: Set<String> = schemaVersion == 4 ? ["default","office","gala","recline"] : ["default","office","gala","recline","recline_office","recline_gala"]
        guard [4,5].contains(schemaVersion), Set(sets.keys) == expected else { throw PreviewError.invalidManifest }
        if schemaVersion == 5 {
            for key in ["default","office","gala"] {
                guard ["rise","lower","jumping","running_left","running_right"].allSatisfy({sets[key]?.sequences[$0] != nil}) else { throw PreviewError.invalidManifest }
            }
            for key in ["recline","recline_office","recline_gala"] {
                guard ["idle","working","waiting","gaze_head","verified_success"].allSatisfy({sets[key]?.sequences[$0] != nil}) else { throw PreviewError.invalidManifest }
            }
        }
        for set in sets.values { _ = try set.validated() }
        return self
    }
}

func runReactiveTests() throws {
    func expect(_ p: Bool) throws { if !p { throw PreviewError.invalidManifest } }
    let box = CGRect(x:0,y:0,width:200,height:300)
    for i in 0..<16 {
        let angle = Double(i)*2*Double.pi/16
        let p = CGPoint(x:100+80*sin(angle),y:150+80*cos(angle))
        let name = PointerDirection.name(point:p,character:box,sixteen:true,previous:"")
        try expect(name == String(format:"gaze_%02d",i))
        var follow = ReactiveState(); follow.input(name,now:1)
        try expect(follow.selected(now:1) == name)
    }
    try expect(PointerDirection.name(point:CGPoint(x:100,y:150),character:box,sixteen:true,previous:"") == "gaze_center")
    try expect(PointerDirection.name(point:CGPoint(x:80,y:150),character:box,sixteen:false,previous:"") == "gaze_left")
    var r = ReactiveState()
    r.input("enter", now: 1); try expect(r.selected(now: 1) == "jumping")
    r.setWork(.running, simulation: false, connected: true, celebrate: false, now: 2)
    r.input("drag_start_left", now:2.8); try expect(r.selected(now:2.8) == "running_left")
    r.input("drag_start_right", now:2.9); try expect(r.selected(now:2.9) == "running_right")
    r.input("drag_start", now: 3); r.input("drag_left",now:3.1); try expect(r.selected(now: 3.1) == "running_left")
    r.input("drag_right",now:3.2); try expect(r.selected(now:3.2) == "running_right")
    r.input("release", now: 4); try expect(r.selected(now: 4) == "settle"); try expect(r.selected(now:4.7) == "working")
    r.setWork(.completed_unverified, simulation: false, connected: true, celebrate: false, now: 5)
    try expect(r.selected(now: 5) == "idle")
    r.setWork(.verified_success, simulation: false, connected: true, celebrate: true, now: 6)
    try expect(r.selected(now: 6) == "verified_success"); try expect(r.selected(now: 10) != "verified_success")
    func event(_ n: Int, _ state: String, instance: String = "a", task: String = "t", evidence: Bool = false) throws -> StatusEvent {
        var o: [String: Any] = ["schema_version":"twos.nyra.status.v1","producer_instance_id":instance,"event_id":"e\(n)","sequence":n,"timestamp":"2026-10-26T00:00:00Z","session_id":"s","task_id":task,"state":state,"source":"twos_runtime","simulation":false]
        if evidence { o["evidence_ref"] = "opaque-verification-id" }
        return try StatusEvent.decode(JSONSerialization.data(withJSONObject: o),simulation: false)
    }
    var reducer = StatusReducer()
    try expect(!reducer.receive(event(1,"verified_success",evidence:true),now:1).celebrate)
    try expect(!reducer.receive(event(1,"verified_success",evidence:true),now:2).celebrate)
    _ = reducer.receive(try event(2,"running",task:"new"),now:3)
    try expect(reducer.receive(event(3,"verified_success",task:"new",evidence:true),now:4).celebrate)
    try expect(!reducer.receive(event(3,"verified_success",task:"new",evidence:true),now:5).celebrate)
    reducer.disconnect(); try expect(!reducer.receive(event(4,"verified_success",task:"new",evidence:true),now:6).celebrate)
    try expect(!reducer.receive(event(6,"verified_success",task:"new",evidence:true),now:7).celebrate)
    try expect(!reducer.receive(event(1,"verified_success",instance:"restart",evidence:true),now:8).celebrate)
    do { _ = try event(8,"verified_success"); throw NSError(domain:"missing evidence accepted",code:1) } catch PreviewError.invalidManifest {}
    var immutable = StatusReducer()
    let initial = try event(1,"running")
    try expect(immutable.receive(initial,now:1).accepted)
    try expect(!immutable.receive(event(1,"failed"),now:2).accepted)
    try expect(immutable.current == initial && !immutable.connected)
    try expect(immutable.receive(initial,now:3).accepted)
    let repeated = immutable.receive(initial,now:4)
    try expect(repeated.accepted && !repeated.changed && !repeated.celebrate)
    r.setWork(.verified_success,simulation:false,connected:true,celebrate:true,now:20)
    try expect(r.selected(now:20.1) == "verified_success")
    r.input("drag_start",now:20.2); try expect(r.selected(now:20.3) == "running_right")
    r.input("release",now:20.4)
    var altered = try JSONSerialization.jsonObject(with: JSONEncoderForTest.event(initial)) as! [String:Any]
    altered["sequence"] = 2
    try expect(!immutable.receive(StatusEvent.decode(JSONSerialization.data(withJSONObject:altered),simulation:false),now:5).accepted)
    r.setWork(.running,simulation:false,connected:true,celebrate:false,now:30)
    r.beginPreview("jumping",duration:2,now:30)
    r.setWork(.running,simulation:false,connected:true,celebrate:false,now:30.5)
    r.input("enter",now:30.6)
    try expect(r.selected(now:31) == "jumping" && r.work == .running && !r.simulation)
    r.expireVisuals(now:32.1); try expect(r.selected(now:32.1) == "working" && !r.debugTrial)
    for state in [WorkState.partial,.failed,.cancelled,.completed_unverified,.disconnected,.idle] {
        r.setWork(state,simulation:false,connected:state != .disconnected,celebrate:false,now:40)
        try expect(r.selected(now:40) == "idle")
    }
    var hover = HoverEdgeTracker()
    try expect(hover.observe(point:CGPoint(x:50,y:50),alphaHit:true,character:box) == "enter")
    try expect(hover.observe(point:CGPoint(x:50,y:50),alphaHit:false,character:box) == nil)
    try expect(hover.observe(point:CGPoint(x:205,y:50),alphaHit:false,character:box) == nil)
    try expect(hover.observe(point:CGPoint(x:220,y:50),alphaHit:false,character:box) == "leave")
    try expect(hover.observe(point:CGPoint(x:50,y:50),alphaHit:true,character:box) == "enter")
    var cooled = ReactiveState(); cooled.input("enter",now:1); cooled.input("enter",now:1.7)
    try expect(cooled.transientUntil == 2.5)
    cooled.input("enter",now:3); try expect(cooled.transientUntil == 4.5)
    var pose = PoseArbiter(); pose.reset(reclining:true)
    try expect(pose.resolve(reclining:true,action:"running_left",now:0) == "rise")
    try expect(pose.resolve(reclining:true,action:"running_right",now:0.1) == "rise")
    try expect(pose.resolve(reclining:true,action:"running_right",now:0.4) == "running_right")
    try expect(pose.resolve(reclining:true,action:"idle",now:0.5) == "lower")
    try expect(pose.resolve(reclining:true,action:"working",now:0.9) == "working" && pose.phase == .reclining)
    try expect(pose.resolve(reclining:false,action:"jumping",now:1) == "jumping" && pose.phase == .standing)
    pose.reset(reclining:true)
    _ = pose.resolve(reclining:true,action:"jumping",now:2)
    _ = pose.resolve(reclining:true,action:"idle",now:2.4)
    try expect(pose.resolve(reclining:true,action:"idle",now:2.5) == "lower")
    try expect(pose.resolve(reclining:true,action:"running_left",now:2.6) == "rise")
    reducer.expire(now:14); try expect(!reducer.connected)
    print("PASS: reactive priority, unverified completion, once-only success, duplicate/gap/reconnect/restart/task isolation, evidence requirement, heartbeat timeout")
}

private enum JSONEncoderForTest {
    static func event(_ e: StatusEvent) throws -> Data {
        var o:[String:Any] = ["schema_version":e.schema_version,"producer_instance_id":e.producer_instance_id,"event_id":e.event_id,"sequence":e.sequence,"timestamp":e.timestamp,"session_id":e.session_id,"task_id":e.task_id as Any? ?? NSNull(),"state":e.state.rawValue,"source":e.source,"simulation":e.simulation]
        if let evidence=e.evidence_ref { o["evidence_ref"]=evidence }
        return try JSONSerialization.data(withJSONObject:o)
    }
}
