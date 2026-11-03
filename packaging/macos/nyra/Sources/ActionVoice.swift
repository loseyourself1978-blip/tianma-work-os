import Foundation

// Fixed local phrases only. Never narrate a task, chat, attachment or credential.
enum VoiceCue: String, CaseIterable {
    case welcome, rest, working, waiting, success, sad, outfit, wave
    var label: String {
        switch self {
        case .welcome: return "问候 / Greeting"
        case .rest: return "休息 / Rest"
        case .working: return "工作 / Working"
        case .waiting: return "等待确认 / Waiting"
        case .success: return "庆祝 / Celebrate"
        case .sad: return "鼓励 / Encouragement"
        case .outfit: return "换装 / Outfit"
        case .wave: return "挥手 / Wave"
        }
    }
    func phrase(_ language: String) -> String {
        let zh = language == "zh"
        switch self {
        case .welcome: return zh ? "嗨，我在这里，陪着你呢。" : "Hi! I'm right here with you."
        case .rest: return zh ? "累了吗？喝口水，休息一下吧。" : "Feeling tired? Have a sip of water and take a little break."
        case .working: return zh ? "开工啦，我陪你一起加油。" : "Let's get started! I'm cheering you on."
        case .waiting: return zh ? "需要你确认一下哦，我在这里等你。" : "Your confirmation is needed. I'll wait right here."
        case .success: return zh ? "欧耶！你好棒！" : "Yay! You did great!"
        case .sad: return zh ? "别着急，我们慢慢来。" : "Don't worry. Let's take it one step at a time."
        case .outfit: return zh ? "换好啦，好看吗？" : "All dressed up! How do I look?"
        case .wave: return zh ? "嘿，我在呢。" : "Hey! I'm here."
        }
    }
    static func previewAnimation(_ name: String) -> VoiceCue? {
        switch name {
        case "verified_success": return .success
        case "working": return .working
        case "waiting": return .waiting
        case "failed": return .sad
        case "waving", "jumping": return .wave
        default: return nil
        }
    }
    static func live(previous: StatusEvent?, current: StatusEvent, decision: SnapshotDecision, wasConnected: Bool) -> VoiceCue? {
        // First snapshot, reconnect, repeated receipt and simulation are silent.
        guard decision.accepted, wasConnected, !current.simulation,
              let previous = previous, previous.producer_instance_id == current.producer_instance_id,
              previous.session_id == current.session_id,
              previous.sequence < current.sequence, previous.state != current.state else { return nil }
        if decision.celebrate { return .success }
        switch current.state {
        case .running: return .working
        case .waiting_user: return .waiting
        case .failed: return .sad
        default: return nil // partial, cancelled and unverified must not celebrate.
        }
    }
}

struct ActionVoiceGate {
    private var consumed: Set<String> = []
    private var order: [String] = []
    private var lastAny = -Double.infinity
    private var lastCue: [VoiceCue: TimeInterval] = [:]
    // No deferred audio queue: suppressed cues are consumed, never replayed later.
    mutating func allow(_ cue: VoiceCue, event: String, now: TimeInterval,
                        enabled: Bool, visible: Bool, busy: Bool) -> Bool {
        guard !consumed.contains(event) else { return false }
        consumed.insert(event); order.append(event)
        if order.count > 256 { consumed.remove(order.removeFirst()) }
        guard now.isFinite, enabled, visible, !busy else { return false }
        let cooldown: TimeInterval = cue == .rest || cue == .wave ? 120 : 45
        guard now-lastAny >= 10, now-(lastCue[cue] ?? -.infinity) >= cooldown else { return false }
        lastAny = now; lastCue[cue] = now
        return true
    }
}

func runActionVoiceTests() throws {
    func require(_ ok: Bool) throws { if !ok { throw PreviewError.invalidManifest } }
    var gate = ActionVoiceGate()
    try require(gate.allow(.rest,event:"one",now:0,enabled:true,visible:true,busy:false))
    try require(!gate.allow(.rest,event:"one",now:200,enabled:true,visible:true,busy:false))
    try require(!gate.allow(.working,event:"two",now:5,enabled:true,visible:true,busy:false))
    try require(gate.allow(.working,event:"three",now:12,enabled:true,visible:true,busy:false))
    try require(!gate.allow(.working,event:"four",now:30,enabled:true,visible:true,busy:false))
    try require(!gate.allow(.success,event:"muted",now:100,enabled:false,visible:true,busy:false))
    try require(!gate.allow(.success,event:"muted",now:200,enabled:true,visible:true,busy:false))
    try require(!gate.allow(.success,event:"hidden",now:200,enabled:true,visible:false,busy:false))
    try require(!gate.allow(.success,event:"overlap",now:200,enabled:true,visible:true,busy:true))
    try require(gate.allow(.success,event:"good",now:200,enabled:true,visible:true,busy:false))
    try require(!gate.allow(.rest,event:"clock",now:10,enabled:true,visible:true,busy:false))
    try require(gate.allow(.rest,event:"next",now:400,enabled:true,visible:true,busy:false))
    func event(_ state: WorkState, _ seq: UInt64 = 2, simulation: Bool = false) -> StatusEvent {
        StatusEvent(schema_version:"twos.nyra.status.v1",producer_instance_id:"TEST",event_id:"TEST-\(seq)",sequence:seq,timestamp:"2026-11-03T00:00:00Z",session_id:"TEST",task_id:"TEST",state:state,source:"twos_runtime",simulation:simulation,evidence_ref:"TEST",activity_side:nil)
    }
    let yes = SnapshotDecision(accepted:true,changed:true,celebrate:false)
    let success = SnapshotDecision(accepted:true,changed:true,celebrate:true)
    try require(VoiceCue.live(previous:nil,current:event(.running),decision:yes,wasConnected:false) == nil)
    try require(VoiceCue.live(previous:event(.idle,1),current:event(.running),decision:yes,wasConnected:true) == .working)
    try require(VoiceCue.live(previous:event(.running,1),current:event(.running),decision:yes,wasConnected:true) == nil)
    try require(VoiceCue.live(previous:event(.running,1),current:event(.verified_success),decision:success,wasConnected:false) == nil)
    try require(VoiceCue.live(previous:event(.running,1),current:event(.verified_success),decision:success,wasConnected:true) == .success)
    for state in [WorkState.partial,.cancelled,.completed_unverified,.disconnected,.activity_unknown,.idle] {
        try require(VoiceCue.live(previous:event(.running,1),current:event(state),decision:yes,wasConnected:true) == nil)
    }
    try require(VoiceCue.live(previous:event(.idle,1),current:event(.running,2,simulation:true),decision:yes,wasConnected:true) == nil)
    try require(VoiceCue.live(previous:event(.idle,3),current:event(.running),decision:yes,wasConnected:true) == nil)
    print("PASS: action audio TEST fixtures — cooldown, mute, hidden, overlap, duplicate, reconnect and truthful completion")
}
