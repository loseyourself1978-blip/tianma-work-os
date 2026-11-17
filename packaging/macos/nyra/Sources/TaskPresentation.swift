import Foundation

// Presentation consumes the authenticated read-only snapshot. Task-control
// availability never decides whether genuine activity is visible.
struct TaskPresentation {
    private var remembered: [String: (row: [String:Any], at: Double)] = [:]
    private var binding: String?
    static let uncertaintyGrace: Double = 8

    static func controlsMatch(event:StatusEvent?,host:String?,session:String?,task:String?)->Bool {
        guard let event=event,let host=host,let session=session,let task=task else{return false}
        return host==event.producer_instance_id && session==event.session_id && task==(event.task_id ?? "")
    }

    mutating func rows(event: StatusEvent?, connected: Bool, lastReceipt: Double,
                       now: Double, controls: [[String:Any]], controlsFresh: Bool) -> [[String:Any]] {
        guard let event = event else { remembered.removeAll(); binding=nil; return [] }
        let nextBinding=event.producer_instance_id+"|"+event.session_id
        if binding != nextBinding {remembered.removeAll();binding=nextBinding}
        let current=connected && now>=lastReceipt && now-lastReceipt<=5
        var output=[[String:Any]]()
        for side in ["left","right"] {
            let observation=event.pane_observations?.first{$0.side==side}
            let label=event.task_labels?.first{$0.side==side}
            if current,let observation=observation,observation.fresh,
               [.running,.queued,.waiting_user].contains(observation.state),let label=label {
                var row:[String:Any]=["side":side,"provider":label.provider,"title":label.title,
                    "state":observation.state.rawValue,"fresh":true,"reason":observation.reason]
                // Controls are optional. The host still revalidates the opaque
                // exact target on every action; a display row grants no authority.
                if controlsFresh,let action=controls.first(where:{
                    $0["side"] as? String==side && $0["provider"] as? String==label.provider &&
                    $0["title"] as? String==label.title && $0["fresh"] as? Bool==true &&
                    ($0["state"] as? String==observation.state.rawValue ||
                     (observation.state == .running && ["stopping","stop_unconfirmed"].contains($0["state"] as? String ?? "")))
                }) {
                    for key in ["target","scope","canAppend","canEdit","canStop","canSteer"] {row[key]=action[key]}
                    row["state"]=action["state"]
                }
                remembered[side]=(row,now);output.append(row)
            } else if current,let observation=observation,observation.fresh,
                      ![.activity_unknown,.disconnected,.running,.queued,.waiting_user].contains(observation.state) {
                // Confirmed ended/idle clears immediately, never a lingering card.
                remembered.removeValue(forKey:side)
            } else if let previous=remembered[side],now>=previous.at,now-previous.at<=Self.uncertaintyGrace {
                var row=previous.row
                row["state"]="activity_unknown";row["fresh"]=false
                for key in ["target","scope","canAppend","canEdit","canStop","canSteer"] {row.removeValue(forKey:key)}
                output.append(row)
            } else {remembered.removeValue(forKey:side)}
        }
        return output
    }
}
