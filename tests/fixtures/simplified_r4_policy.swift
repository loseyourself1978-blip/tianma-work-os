// SIMULATED / TEST ONLY. Uses the production host/ledger, no account or model.
if mode == "simplified_r4_policy" {
    for source in [0,1] {
        var d=PairedDialogue(id:"TEST-R4",providers:["ChatGPT","Claude"],conversations:[base.absoluteString,base.absoluteString],roles:["",""],firstText:"",maxExchanges:0,duration:0,createdAt:1,state:"running",untilStopped:true,checkboxMode:true,firstSource:source,awaitingSeed:true)
        precondition(d.valid && d.nextTarget==1-source && d.deadline == .infinity)
        d.sentCount=501;d.completedCount=501
        precondition(d.valid && !d.roundLimitReached && d.nextTarget==source)
        let restored=try! JSONDecoder().decode(PairedDialogue.self,from:JSONEncoder().encode(d))
        precondition(restored.valid && restored.firstSource==source && restored.awaitingSeed==true)
        d.stopOnConcession=true;precondition(!d.valid,"checkbox cannot inherit concession stop")
        d.stopOnConcession=false;d.untilStopped=false;precondition(!d.valid,"checkbox cannot inherit a hidden finite budget")
    }
    try! NativeWorkbench.save(["kind0":"ChatGPT","kind1":"Claude","url0":base.absoluteString,"url1":base.absoluteString],at:prefs.appendingPathComponent("paired-workbench.json"))
    let work=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("no business action")})
    work.dialogue=PairedDialogue(id:"TEST-WAIT",providers:["ChatGPT","Claude"],conversations:[base.absoluteString,base.absoluteString],roles:["",""],firstText:"",maxExchanges:0,duration:0,createdAt:1,state:"running",untilStopped:true,checkboxMode:true,firstSource:1,awaitingSeed:true)
    work.setAutomaticReplies(false,from:0,source:base)
    precondition(work.dialogue?.state=="stopped" && work.webTransfers.isEmpty)
    work.tickDialogue();precondition(work.webTransfers.isEmpty)
    work.dialogue?.state="running";precondition(work.saveDialogue())
    let restored=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("no business action")})
    precondition(restored.dialogue?.state=="paused" && restored.webTransfers.isEmpty,"restart retains receipt, never auto-starts")
    precondition(restored.webPanes.values.allSatisfy{!$0.automaticReplyEnabled})
    print("SIMULATED_R4_UNBOUNDED_DIRECTION_WAIT_STOP_RESTART_PASS");exit(0)
}
if mode.hasPrefix("simplified_r4_auto_") {
    let side=mode.hasSuffix("right") ? 1 : 0
    let left=base.appendingPathComponent("a"),right=base.appendingPathComponent("b")
    try! NativeWorkbench.save(["kind0":"ChatGPT","kind1":"Claude","url0":left.absoluteString,"url1":right.absoluteString],at:prefs.appendingPathComponent("paired-workbench.json"))
    let work=IntegratedWorkbench(preferences:prefs,resources:resources,translate:{$0},openProjects:{fatalError("no business action")})
    work.start()
    func begin() {
        work.webPanes[side]!.web.evaluateJavaScript("document.getElementById('draft') != null") { loaded,_ in
            guard loaded as? Bool==true,work.webPanes[0]!.web.url==left,work.webPanes[1]!.web.url==right else{DispatchQueue.main.asyncAfter(deadline:.now()+0.1,execute:begin);return}
            let seed="""
            const user=document.createElement('div');user.dataset.messageAuthorRole='user';user.textContent='TEST R4 NEW TOPIC';document.body.append(user);
            const reply=document.createElement('div');reply.dataset.messageAuthorRole='assistant';reply.dataset.isStreaming='false';reply.className='font-claude-response';reply.textContent='TEST R4 COMPLETE SEED';document.body.append(reply);
            """
            let startsEmpty=mode.hasSuffix("empty") || mode.hasSuffix("wait_stop")
            let startsStreaming=mode.hasSuffix("stream")
            let initial=startsEmpty ? "void 0" : seed+(startsStreaming ? "reply.dataset.isStreaming='true';const stop=document.createElement('button');stop.id='test-stop';stop.setAttribute('aria-label','Stop');document.body.append(stop);" : "")
            work.webPanes[side]!.web.evaluateJavaScript(initial) { _,error in
                precondition(error==nil)
                let source=side==0 ? left : right
                if mode.hasSuffix("manual") {
                    work.webPanes[side]!.providerSnapshot(includeReply:true,latestOnly:true) { reply in
                        precondition(reply["state"] as? String=="reply")
                        work.handoff(reply["text"] as! String,source:source,from:side,message:reply["message"] as! String)
                        enable()
                    }
                } else {enable()}
                func enable() {
                    work.setAutomaticReplies(true,from:side,source:source)
                    let id=work.dialogue?.id
                    work.setAutomaticReplies(true,from:1-side,source:side==0 ? right : left)
                    precondition(work.dialogue?.id==id && work.dialogue?.firstSource==side,"near simultaneous enable created another session")
                    precondition(work.dialogueWindow==nil && work.dialogue?.roles==["",""] && work.dialogue?.untilStopped==true)
                    if startsEmpty || startsStreaming {
                        DispatchQueue.main.asyncAfter(deadline:.now()+0.5) {
                            precondition(work.webTransfers.isEmpty,"incomplete/absent seed dispatched")
                            if mode.hasSuffix("wait_stop") {work.setAutomaticReplies(false,from:1-side,source:side==0 ? right : left)}
                            let completed=startsEmpty ? seed : "document.querySelector('[data-is-streaming]').dataset.isStreaming='false';document.getElementById('test-stop').remove();"
                            work.webPanes[side]!.web.evaluateJavaScript(completed) { _,error in
                                precondition(error==nil)
                                if mode.hasSuffix("wait_stop") {
                                    DispatchQueue.main.asyncAfter(deadline:.now()+1) {
                                        work.tickDialogue();precondition(work.dialogue?.state=="stopped" && work.webTransfers.isEmpty)
                                        print("SIMULATED_R4_STOP_WHILE_WAITING_LATE_SEED_NO_SEND_PASS");exit(0)
                                    }
                                }
                            }
                        }
                    }
                    if mode.hasSuffix("wait_stop") {return}
                    func finish() {
                        if work.dialogue?.state=="paused" {fatalError("R4 auto paused: \(work.dialogue?.reason ?? "")")}
                        guard (work.dialogue?.completedCount ?? 0)>=6 else {DispatchQueue.main.asyncAfter(deadline:.now()+0.1,execute:finish);return}
                        precondition(work.webTransfers.prefix(6).map(\.targetPane)==(0..<6).map{$0.isMultiple(of:2) ? 1-side : side})
                        precondition(Set(work.webTransfers.map(\.id)).count==work.webTransfers.count)
                        precondition(work.webTransfers.filter{$0.text=="TEST R4 COMPLETE SEED"}.count==1,"manual in-flight seed was resent")
                        work.setAutomaticReplies(false,from:1-side,source:side==0 ? right : left)
                        let count=work.webTransfers.count
                        if mode.contains("reconcile") {
                            let old=work.dialogue!.id
                            let i=work.webTransfers.firstIndex(where:{$0.state=="reply"})!
                            work.dialogue?.pendingID=work.webTransfers[i].id
                            work.webTransfers[i].state="sent";work.webTransfers[i].result=nil
                            work.webTransfers[i].resultHash=nil;work.webTransfers[i].replyMessage=nil
                            precondition(work.persistWebTransfers() && work.saveDialogue())
                            work.webPanes[side]!.web.evaluateJavaScript("(()=>{"+seed.replacingOccurrences(of:"TEST R4 COMPLETE SEED",with:"TEST R4 NEW AFTER STOP")+"})()") { _,error in
                                precondition(error==nil)
                                work.setAutomaticReplies(true,from:side,source:source)
                                if mode.hasSuffix("reconcile_stop") {
                                    work.setAutomaticReplies(false,from:side,source:source)
                                    DispatchQueue.main.asyncAfter(deadline:.now()+1) {
                                        precondition(work.dialogue?.id==old && work.dialogue?.state=="stopped" && work.webTransfers.count==count)
                                        precondition(!work.dialogueStartPending)
                                        print("SIMULATED_R4_STOP_REVOKES_READONLY_RECONCILE_CALLBACK_PASS");exit(0)
                                    }
                                } else {
                                    func newSeed() {
                                        guard work.webTransfers.count>count else {DispatchQueue.main.asyncAfter(deadline:.now()+0.1,execute:newSeed);return}
                                        work.stopDialogue()
                                        precondition(work.dialogue?.id != old && work.webTransfers[i].state=="reply")
                                        precondition(work.webTransfers.filter{$0.text=="TEST R4 NEW AFTER STOP"}.count==1)
                                        print("SIMULATED_R4_STOPPED_RECEIPT_RECONCILED_WITHOUT_MANUAL_CHECK_PASS");exit(0)
                                    };newSeed()
                                }
                            };return
                        }
                        DispatchQueue.main.asyncAfter(deadline:.now()+1) {
                            work.tickDialogue()
                            precondition(work.dialogue?.state=="stopped" && work.webTransfers.count==count && work.activeWebQueues.isEmpty)
                            print("SIMULATED_R4_SHARED_CHECKBOX_THREE_ROUNDTRIPS_STOP_AND_DEDUP_PASS");exit(0)
                        }
                    };finish()
                }
            }
        }
    };begin();DispatchQueue.main.asyncAfter(deadline:.now()+65){fatalError("R4 fixture timeout")};app.run();exit(0)
}
