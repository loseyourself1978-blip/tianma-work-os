// TEST/FIXTURE ONLY: production reducer/dispatcher, no websites or model run.
if mode == "owner_r3_policy" {
    let now=ProcessInfo.processInfo.systemUptime
    let left=PaneActivity(session:"TEST-LEFT",task:"TEST-TURN",state:"running",at:now,reason:"VISIBLE_GENERATION_CONTROL")
    let unknown=PaneActivity(session:"TEST-RIGHT",task:nil,state:"activity_unknown",at:now,reason:"AMBIGUOUS_COMPOSER")
    precondition(PaneActivity.aggregate([0:left,1:unknown]).state=="running")
    precondition(PaneActivity.aggregate([0:left,1:unknown]).side=="left")
    precondition(PaneActivity.aggregate([0:unknown,1:unknown]).state=="activity_unknown")
    let producer=NyraStatusProducer(directory:prefs.appendingPathComponent("status"),helper:prefs.appendingPathComponent("Missing.app"))
    func read()->[String:Any] {
        var out:[String:Any]?;producer.snapshot {out=try! JSONSerialization.jsonObject(with:$0) as? [String:Any]}
        while out==nil {RunLoop.current.run(until:Date().addingTimeInterval(0.01))};return out!
    }
    let panes=PaneActivity.observations([0:left,1:unknown])
    producer.observe(session:"TEST-PAIR",task:"TEST-TURN",state:"running",source:"twos_runtime",side:"left",panes:panes)
    let a=read();precondition(a["schema_version"] as? String=="twos.nyra.status.v3")
    let event=try! StatusEvent.decode(JSONSerialization.data(withJSONObject:a),simulation:false)
    precondition(event.pane_observations?.last?.state == .activity_unknown)
    var reducer=StatusReducer();precondition(reducer.receive(event,now:100).accepted)
    producer.observe(session:"TEST-PAIR",task:"TEST-TURN",state:"running",source:"twos_runtime",side:"left",panes:panes)
    let same=try! StatusEvent.decode(JSONSerialization.data(withJSONObject:read()),simulation:false)
    let heartbeat=reducer.receive(same,now:102)
    precondition(same==event && !heartbeat.changed && reducer.lastReceipt==102 && reducer.connected)
    precondition(reducer.celebrationCount==0)
    producer.observe(session:"TEST-PAIR",task:nil,state:"activity_unknown",source:"twos_runtime",side:"both",panes:PaneActivity.observations([0:unknown,1:unknown]))
    let uncertain=try! StatusEvent.decode(JSONSerialization.data(withJSONObject:read()),simulation:false)
    precondition(reducer.receive(uncertain,now:104).accepted && reducer.connected,"activity unknown is not a transport failure")
    var injected=read();var badPanes=injected["pane_observations"] as! [[String:Any]];badPanes[0]["body"]="PRIVATE TEST FORBIDDEN";injected["pane_observations"]=badPanes
    do {_ = try StatusEvent.decode(JSONSerialization.data(withJSONObject:injected),simulation:false);fatalError("private extension accepted")}catch{}
    // A live consumer with an old/different producer must not label saved
    // observations Fresh. Heartbeat and snapshot age are separate clocks.
    let recent=NativeNyra.currentPaneObservations(panes,connected:true,snapshotAge:1)
    precondition(recent.allSatisfy { $0["fresh"] as? Bool == true })
    for age:Double? in [nil,7,146.1,-1,Double.infinity,Double.nan] {
        let stale=NativeNyra.currentPaneObservations(panes,connected:true,snapshotAge:age)
        precondition(stale.allSatisfy { $0["fresh"] as? Bool == false })
        precondition(stale.first?["state"] as? String=="running","keep last observation identity; mark stale rather than invent idle")
    }
    let detached=NativeNyra.currentPaneObservations(panes,connected:false,snapshotAge:0.1)
    precondition(detached.allSatisfy { $0["fresh"] as? Bool == false })
    var partiallyStale=panes;partiallyStale[0]["fresh"]=false
    let retained=NativeNyra.currentPaneObservations(partiallyStale,connected:true,snapshotAge:1)
    precondition(retained[0]["fresh"] as? Bool==false && retained[1]["fresh"] as? Bool==true)
    let future=PaneActivity(session:"TEST",task:nil,state:"idle",at:now+100)
    precondition(!future.fresh)
    var d=PairedDialogue(id:"TEST-STOP",providers:["ChatGPT","Claude"],conversations:[base.absoluteString,base.absoluteString],roles:["a","b"],firstText:"TEST ONLY",maxExchanges:0,duration:0,createdAt:1,state:"running",untilStopped:true)
    precondition(d.valid && d.deadline == .infinity && !d.roundLimitReached)
    d.sentCount=200;d.completedCount=200;precondition(d.valid && !d.roundLimitReached,"no hidden fixed debate cap")
    d.sentCount=0;d.completedCount=0
    try! NativeWorkbench.save(["kind0":"ChatGPT","kind1":"Claude","url0":base.absoluteString,"url1":base.absoluteString],at:prefs.appendingPathComponent("paired-workbench.json"))
    let work=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("business action")})
    for side in [0,1] {
        var r=WebHandoffReceipt(source:base.absoluteString,message:"TEST-STOP",text:"TEST ONLY",hash:"test",provider:"Claude",targetPane:1,targetURL:base.absoluteString,binding:"test",dialogueID:d.id)
        r.state="queued";r.mayHaveSent=false
        var flying=r;flying.id=UUID().uuidString;flying.state="sending";flying.mayHaveSent=true
        d.pendingID=flying.id;d.state="running";work.dialogue=d;work.webTransfers=[r,flying];work.activeWebQueues.insert(r.id)
        work.stopDialogueFromPane(side,source:base)
        precondition(work.dialogue?.state=="stopped" && work.activeWebQueues.isEmpty)
        precondition(work.webTransfers[0].state=="cancelled" && work.webTransfers[1].mayHaveSent==true)
        work.applyWebResponse(flying.id,response:["state":"reply","reply":"TEST ONLY LATE","conversationURL":base.absoluteString])
        work.tickDialogue();precondition(work.webTransfers.count==2 && work.dialogue?.state=="stopped","late reply must not restart relay")
    }
    var interrupted=WebHandoffReceipt(source:base.absoluteString,message:"TEST-INTERRUPTED",text:"TEST ONLY",hash:"test",provider:"Claude",targetPane:1,targetURL:base.absoluteString,binding:"test",dialogueID:d.id)
    interrupted.state="sent";interrupted.mayHaveSent=true;work.webTransfers=[interrupted]
    d.pendingID=interrupted.id;d.state="running";work.dialogue=d
    work.applyWebResponse(interrupted.id,response:["state":"generation_stopped","reason":"PROVIDER_REPLY_INTERRUPTED","conversationURL":base.absoluteString])
    precondition(work.webTransfers[0].state=="generation_stopped" && work.webTransfers[0].mayHaveSent==true && work.webTransfers[0].result==nil)
    precondition(work.dialogue?.state=="stopped")
    work.applyWebResponse(interrupted.id,response:["state":"unknown"])
    work.tickDialogue();precondition(work.webTransfers.count==1 && work.webTransfers[0].state=="generation_stopped")
    work.dialogueStartToken=UUID().uuidString;work.dialogueStartPending=true;work.stopDialogue()
    precondition(work.dialogueStartToken==nil && !work.dialogueStartPending)
    // Editing a previously selected seed must revoke its stale identity and
    // pending validation, without modifying a frozen active exchange.
    let editor=NSTextView();work.dialogueText=editor;editor.string="TEST ONLY NEW FIRST TEXT"
    work.dialogueSeed=(base.absoluteString,"OLD-SEED","OLD-HASH")
    work.dialogueStartToken=UUID().uuidString;work.dialogueStartPending=true
    let frozenFirst=work.dialogue?.firstText
    work.textDidChange(Notification(name:NSText.didChangeNotification,object:editor))
    precondition(work.dialogueSeed==nil && work.dialogueStartToken==nil && !work.dialogueStartPending)
    precondition(work.dialogue?.firstText==frozenFirst)
    let restored=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("business action")})
    precondition(restored.dialogue?.state=="stopped" && restored.activeWebQueues.isEmpty)
    print("R3_STOP_BOTH_SIDES_LATE_REPLY_UNBOUNDED_AND_ACTIVITY_TRUTH_PASS");exit(0)
}
