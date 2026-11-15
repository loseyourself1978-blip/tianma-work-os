import AppKit

enum CompanionControlText {
    static func error(_ code:String,zh:Bool)->String {
        let values:[String:[String]]=[
            "connection":["连接已变化；输入仍保留。回到 TWOS 核对原任务。","The connection changed. Your input is retained; check the original task in TWOS."],
            "changed":["任务或草稿已变化；没有改发。请回到 TWOS 核对。","The task or draft changed. Nothing was redirected; review it in TWOS."],
            "readonly":["此任务不能由 TWOS 控制，请在原控制端操作。","TWOS cannot control this task. Use its original controller."],
            "unknown":["操作结果尚未确认；请回到 TWOS 核对，不要重复发送。","The result is unconfirmed. Check TWOS before sending again."],
            "saving":["草稿未保存；输入仍保留，请检查本机存储。","The draft was not saved. Your input is retained; check local storage."],
            "stale":["任务状态待更新；输入仍保留，请在 TWOS 核对。","Task state needs an update. Your input is retained; review it in TWOS."],
            "focus":["尚未确认工作台已显示，请从 Dock 打开已连接的 TWOS。","The workbench is not confirmed visible. Open the connected TWOS from the Dock."],
            "pending":["上一个操作仍在处理，请稍候。","The previous operation is still pending."],
            "unsupported":["当前版本不支持此操作，请在 TWOS 中继续。","This operation is unavailable in the current version. Continue in TWOS."]]
        let key:String
        if code.contains("DRAFT_CHANGED") || code.contains("TASK_CHANGED") || code=="INPUT_ALREADY_DISPATCHED" {key="changed"}
        else if code.contains("NOT_SAVED") {key="saving"}
        else if code.contains("OBSERVATION_STALE") {key="stale"}
        else if code.contains("READ_ONLY") || code.contains("NOT_CONTROLLED") || code.contains("NOT_AUTHORIZED") {key="readonly"}
        else if code.contains("FOCUS") || code.contains("WINDOW_MISSING") {key="focus"}
        else if code.contains("PENDING") || code=="REQUEST_IN_FLIGHT" {key="pending"}
        else if code.contains("HOST_") || code=="peerChanged" || code=="controlUnavailable" {key="connection"}
        else if code.contains("UNAVAILABLE") || code.contains("UNSUPPORTED") {key="unsupported"}
        else {key="unknown"}
        return values[key]![zh ? 0:1]
    }
}

enum CompanionEditorMenu {
    static func install(in menu:NSMenu) {
        let edit=NSMenu(title:"Edit / 编辑")
        for (title,action,key) in [("Undo / 撤销","undo:","z"),("Redo / 重做","redo:","Z"),("Cut / 剪切","cut:","x"),("Copy / 复制","copy:","c"),("Paste / 粘贴","paste:","v"),("Select All / 全选","selectAll:","a")] {
            edit.addItem(withTitle:title,action:Selector(action),keyEquivalent:key)
        }
        let item=NSMenuItem(title:edit.title,action:nil,keyEquivalent:"");item.submenu=edit;menu.addItem(item)
    }
}

final class CompanionTaskPanel:NSPanel {
    override var canBecomeKey:Bool{false}
    override var canBecomeMain:Bool{false}
}
final class CompanionInputPanel:NSPanel {
    override var canBecomeKey:Bool{true}
    override var canBecomeMain:Bool{false}
}
// The bubble is a non-key overlay. Its controls must handle the initial mouse
// press without asking this panel to take keyboard focus from the workbench.
final class CompanionActionButton:NSButton {
    override func acceptsFirstMouse(for event:NSEvent?)->Bool {true}
    override var needsPanelToBecomeKey:Bool {false}
}
final class CompanionTaskPicker:NSPopUpButton {
    override func acceptsFirstMouse(for event:NSEvent?)->Bool {true}
    override var needsPanelToBecomeKey:Bool {false}
}
final class CompanionTaskCard:NSObject {
    let panel=CompanionTaskPanel(contentRect:NSRect(x:0,y:0,width:300,height:64),styleMask:[.borderless,.nonactivatingPanel],backing:.buffered,defer:false)
    let backdrop=NSVisualEffectView()
    let picker=CompanionTaskPicker(frame:.zero,pullsDown:false)
    let title=TaskLabelButton()
    let subtitle=TaskLabelButton()
    let expand=CompanionActionButton(title:"",target:nil,action:nil)
    let append=CompanionActionButton(title:"",target:nil,action:nil)
    let stop=CompanionActionButton(title:"",target:nil,action:nil)
    var expanded=false
    var lastAnchor:NSRect?,lastScreen:NSScreen?
    var rows:[[String:Any]]=[]
    var selected:String?
    var onAction:((String)->Void)?
    var onFocus:((String)->Void)?
    var onAppend:(([String:Any])->Void)?
    var onStop:(([String:Any],String)->Void)?
    struct StopAttempt {
        let id:String,target:String,started:Double,at:Double
        var response:String?,error:String?,finished:Double?
    }
    var stopAttempt:StopAttempt?
    var stopObservation:[String:Any] {
        guard let attempt=stopAttempt else{return [:]}
        var value:[String:Any]=["id":attempt.id,"target":attempt.target,"clickedAt":attempt.at,
            "elapsedMs":Int(max(0,(attempt.finished ?? ProcessInfo.processInfo.systemUptime)-attempt.started)*1000),
            "response":attempt.response ?? "awaiting_response"]
        if let error=attempt.error{value["error"]=error}
        return value
    }
    func finishStop(_ id:String,target:String,result:[String:Any]) {
        // A late callback cannot change another task or a newer user action.
        guard var attempt=stopAttempt,attempt.id==id,attempt.target==target else{return}
        attempt.finished=ProcessInfo.processInfo.systemUptime
        attempt.response=result["state"] as? String
        attempt.error=result["error"] as? String
        if attempt.response != "stopping" && attempt.error==nil {attempt.error="STOP_TERMINAL_NOT_CONFIRMED"}
        stopAttempt=attempt;render();onAction?("stop_response")
    }
    var task:[String:Any]?{rows.first{$0["target"] as? String==selected} ?? rows.first}
    override init(){
        super.init();panel.isReleasedWhenClosed=false;panel.isOpaque=false;panel.backgroundColor = .clear;panel.level = NSWindow.Level(rawValue:NSWindow.Level.floating.rawValue+1);panel.hidesOnDeactivate=false;panel.title="Nyra · Task controls"
        panel.collectionBehavior=[.canJoinAllSpaces,.fullScreenAuxiliary];panel.hasShadow=true
        backdrop.frame=panel.contentView!.bounds;backdrop.autoresizingMask=[.width,.height]
        backdrop.material = .popover;backdrop.blendingMode = .behindWindow;backdrop.state = .active
        backdrop.wantsLayer=true;backdrop.layer?.cornerRadius=30;backdrop.layer?.masksToBounds=true
        backdrop.layer?.borderWidth=0.5;backdrop.layer?.borderColor=NSColor.separatorColor.cgColor;panel.contentView=backdrop
        picker.target=self;picker.action=#selector(selectTask)
        for label in [title,subtitle] {
            label.target=self;label.action=#selector(focus);label.layer?.backgroundColor=NSColor.clear.cgColor
            label.cell?.wraps=false;label.cell?.isScrollable=false;label.cell?.lineBreakMode = .byTruncatingTail
            label.cell?.truncatesLastVisibleLine=true;label.contentTintColor = .labelColor
        }
        title.font = .systemFont(ofSize:13,weight:.semibold);subtitle.font = .systemFont(ofSize:11)
        subtitle.contentTintColor = .secondaryLabelColor
        expand.isBordered=false;expand.target=self;expand.action=#selector(toggleExpanded)
        append.target=self;append.action=#selector(edit);stop.target=self;stop.action=#selector(stopTask)
        for v in [picker,title,subtitle,expand,append,stop] as [NSView]{backdrop.addSubview(v)}
        layout()
    }
    static func state(_ key:String,zh:Bool)->String {
        let labels=["running":["正在执行","Running"],"queued":["排队","Queued"],"waiting_user":["等待你的操作","Waiting for you"],"idle":["执行已结束 · 待核验","Execution ended · unverified"],"completed_unverified":["执行已结束 · 待核验","Execution ended · unverified"],"verified_success":["已核验成功","Verified success"],"partial":["部分完成","Partial"],"failed":["失败","Failed"],"cancelled":["已停止","Stopped"],"stopping":["正在停止","Stopping"],"stop_unconfirmed":["停止未确认","Stop unconfirmed"]]
        return labels[key]?[zh ? 0:1] ?? (zh ? "状态待更新":"Status awaiting update")
    }
    var zh=false,fresh=false,authorized=false
    func update(_ rows:[[String:Any]],fresh:Bool,authorized:Bool,zh:Bool){
        let previous=task
        self.rows=rows;self.fresh=fresh;self.authorized=authorized;self.zh=zh
        if !rows.contains(where:{$0["target"] as? String==selected}) {
            // A turn changes the action target, not the user's chosen side/chat.
            // The editor separately freezes the exact target at the time of click.
            let same=rows.first { row in
                guard let scope=previous?["scope"] as? String,!scope.isEmpty else{return false}
                return row["scope"] as? String==scope
            }
            let active=rows.first{["running","queued","waiting_user"].contains($0["state"] as? String ?? "")}
            selected=(same ?? active ?? rows.first)?["target"] as? String
        }
        let labels=rows.map{($0["side"] as? String=="left" ? (zh ? "左侧":"Left"):(zh ? "右侧":"Right"))+" · "+($0["provider"] as? String ?? "")}
        if picker.itemTitles != labels {picker.removeAllItems();picker.addItems(withTitles:labels)}
        if let index=rows.firstIndex(where:{$0["target"] as? String==selected}){picker.selectItem(at:index)}
        picker.setAccessibilityLabel(zh ? "当前任务":"Current task");render()
    }
    func render(){
        guard let task=task else{panel.orderOut(nil);return}
        let current=fresh && task["fresh"] as? Bool==true
        let taskState=task["state"] as? String ?? ""
        let terminal=["idle","completed_unverified","verified_success","partial","failed","cancelled"].contains(taskState)
        let attempt=stopAttempt.flatMap{$0.target==task["target"] as? String ? $0:nil}
        let stopping=attempt != nil && !terminal
        var state=current ? Self.state(taskState,zh:zh):(zh ? "状态待更新":"Status awaiting update")
        var stopDetail:String?
        if current,stopping,let attempt=attempt {
            if let error=attempt.error {
                state=zh ? "停止未确认":"Stop unconfirmed"
                stopDetail=CompanionControlText.error(error,zh:zh)
            } else if ProcessInfo.processInfo.systemUptime-attempt.started>=12 {
                state=zh ? "停止未确认":"Stop unconfirmed"
                stopDetail=zh ? "尚未收到终态；请在 TWOS 核对，不会自动重试。":"No terminal state received. Check TWOS; no automatic retry."
            } else {state=zh ? "正在停止…":"Stopping…"}
        }
        title.title=task["title"] as? String ?? (zh ? "标题暂不可用":"Title unavailable");title.isHidden=false
        let side=task["side"] as? String=="left" ? (zh ? "左侧":"Left"):(zh ? "右侧":"Right")
        subtitle.title=side+" · "+(task["provider"] as? String ?? "")+" · "+state;subtitle.isHidden=false
        title.setAccessibilityLabel(title.title+(zh ? " · 返回 TWOS":" · Return to TWOS"))
        subtitle.setAccessibilityLabel(subtitle.title)
        title.toolTip=title.title;subtitle.toolTip=stopDetail ?? task["reason"] as? String
        expand.image=NSImage(systemSymbolName:expanded ? "chevron.up":"chevron.down",accessibilityDescription:zh ? (expanded ? "收起任务操作":"展开任务操作"):(expanded ? "Hide task controls":"Show task controls"))
        expand.setAccessibilityLabel(zh ? (expanded ? "收起任务操作":"展开任务操作"):(expanded ? "Hide task controls":"Show task controls"))
        append.title="";append.isBordered=false
        append.image=NSImage(systemSymbolName:"square.and.pencil",accessibilityDescription:zh ? "编辑指令":"Edit input")
        append.setAccessibilityLabel(zh ? "编辑指令":"Edit input")
        stop.title="";stop.isBordered=false
        stop.image=NSImage(systemSymbolName:"stop.fill",accessibilityDescription:zh ? "停止":"Stop")
        stop.setAccessibilityLabel(zh ? "停止当前任务":"Stop current task")
        append.isEnabled=current && authorized && (task["canEdit"] as? Bool ?? task["canAppend"] as? Bool ?? false)
        stop.isEnabled=current && authorized && task["canStop"] as? Bool==true && attempt==nil
        stop.toolTip=stop.isEnabled ? (zh ? "停止已选任务及其待发队列":"Stop the selected task and its queued input") :
            stopDetail ?? (!current ? (zh ? "状态待更新，请在 TWOS 核对":"Status awaiting update; check TWOS") :
                terminal ? (zh ? "此执行已结束，无需再次停止":"This execution has ended; nothing remains to stop") :
                stopping || taskState=="stopping" ? (zh ? "已请求停止，正在等待真实终态":"Stop requested; waiting for the actual terminal state") :
                !authorized ? (zh ? "请在 TWOS 授权任务控制":"Authorize task controls in TWOS") :
                (zh ? "此任务不能由 TWOS 停止，请在原控制端操作":"TWOS cannot stop this task; use its original controller"))
        stop.setAccessibilityHelp(stop.toolTip)
        let unavailable = !current ? (zh ? "状态待更新；请回到 TWOS 核对连接":"Status awaiting update; check the connection in TWOS") : !authorized ? (zh ? "在 TWOS 连接并授权任务控制":"Connect and authorize task controls in TWOS") : (zh ? "此任务由原客户端控制；请在原客户端编辑":"This task belongs to its original controller; edit it there")
        append.toolTip=append.isEnabled ? (zh ? "打开已选任务的指令编辑器":"Open the selected task's input editor"):unavailable
        if !append.isEnabled {append.toolTip=unavailable}
        layout()
    }
    func layout(){
        let height:CGFloat=expanded && rows.count>1 ? 100:64
        if panel.frame.height != height {panel.setContentSize(NSSize(width:300,height:height))}
        backdrop.layer?.cornerRadius=expanded ? 20:30
        let controlsWidth:CGFloat=rows.count>1 ? 86:62
        title.frame=NSRect(x:14,y:height-29,width:272-controlsWidth,height:20)
        subtitle.frame=NSRect(x:14,y:height-49,width:272-controlsWidth,height:18)
        expand.isHidden=rows.count<2;expand.frame=NSRect(x:270,y:height-47,width:24,height:30)
        picker.isHidden = !expanded || rows.count<2;picker.frame=NSRect(x:12,y:8,width:276,height:26)
        // Editing and stopping are direct actions, never hidden behind expansion.
        append.isHidden=false;stop.isHidden=false
        append.frame=NSRect(x:300-controlsWidth,y:height-47,width:28,height:30)
        stop.frame=NSRect(x:330-controlsWidth,y:height-47,width:28,height:30)
        if let anchor=lastAnchor,let screen=lastScreen{position(anchor:anchor,screen:screen)}
    }
    @objc func toggleExpanded(){expanded.toggle();render();onAction?(expanded ? "expanded":"collapsed")}
    @objc func selectTask(){guard rows.indices.contains(picker.indexOfSelectedItem) else{return};selected=rows[picker.indexOfSelectedItem]["target"] as? String;render()}
    @objc func focus(){if let target=task?["target"] as? String{onFocus?(target)}}
    @objc func edit(){guard append.isEnabled,let task=task else{return};onAction?("append_clicked");onAppend?(task)}
    @objc func stopTask(){
        guard stop.isEnabled,let task=task,let target=task["target"] as? String,let action=onStop else{return}
        let id=UUID().uuidString
        stopAttempt=StopAttempt(id:id,target:target,started:ProcessInfo.processInfo.systemUptime,at:Date().timeIntervalSince1970)
        render();onAction?("stop_clicked");action(task,id)
    }
    func position(anchor:NSRect,screen:NSScreen){
        lastAnchor=anchor;lastScreen=screen
        let safe=screen.visibleFrame.insetBy(dx:8,dy:8),size=panel.frame.size
        let y=anchor.minY-size.height-4>=safe.minY ? anchor.minY-size.height-4:min(safe.maxY-size.height,anchor.maxY+4)
        panel.setFrameOrigin(NSPoint(x:max(safe.minX,min(anchor.midX-size.width/2,safe.maxX-size.width)),y:max(safe.minY,y)))
    }
}

final class CompanionTaskEditor:NSObject,NSTextViewDelegate,NSWindowDelegate {
    let task:[String:Any],target:String,zh:Bool
    let panel=CompanionInputPanel(contentRect:NSRect(x:0,y:0,width:360,height:190),styleMask:[.borderless],backing:.buffered,defer:false)
    let text=NSTextView(),mode=NSPopUpButton(frame:.zero,pullsDown:false),pending=NSPopUpButton(frame:.zero,pullsDown:false)
    let status=NSTextField(labelWithString:"")
    let send=CompanionActionButton(title:"",target:nil,action:nil)
    var request:((String,[String:Any],@escaping([String:Any])->Void)->Void)?
    var revision="",queueID:String?,queues:[[String:String]]=[]
    var maySubmit=true
    var pendingSubmit:String?,unconfirmedReceipt:String?,receiptGeneration=0,dismissed=false
    var recovery:CompanionDraftRecovery?,recoveryID:String?,restoredRecovery=false
    let useSaved=CompanionActionButton(title:"",target:nil,action:nil)
    var busy=false,loading=false,dirty=false,operation:String?,saveTimer:Timer?,closed:((CompanionTaskEditor)->Void)?
    init(task:[String:Any],zh:Bool){
        self.task=task;target=task["target"] as? String ?? "";self.zh=zh;super.init()
        panel.isReleasedWhenClosed=false;panel.level = NSWindow.Level(rawValue:NSWindow.Level.floating.rawValue+2);panel.hidesOnDeactivate=false;panel.delegate=self;panel.collectionBehavior=[.canJoinAllSpaces,.fullScreenAuxiliary]
        panel.title=(task["provider"] as? String ?? "")+" · "+(task["title"] as? String ?? "")
        panel.isOpaque=false;panel.backgroundColor = .clear;panel.hasShadow=true
        let backdrop=NSVisualEffectView(frame:panel.contentView!.bounds)
        backdrop.material = .popover;backdrop.blendingMode = .behindWindow;backdrop.state = .active
        backdrop.wantsLayer=true;backdrop.layer?.cornerRadius=20;backdrop.layer?.masksToBounds=true
        panel.contentView=backdrop
        let heading=NSTextField(labelWithString:panel.title);heading.frame=NSRect(x:14,y:161,width:300,height:18)
        heading.font = .systemFont(ofSize:12,weight:.semibold);heading.lineBreakMode = .byTruncatingTail;heading.toolTip=panel.title
        pending.frame=NSRect(x:10,y:156,width:306,height:26);pending.target=self;pending.action=#selector(selectQueued);pending.isHidden=true
        let scroll=NSScrollView(frame:NSRect(x:12,y:54,width:336,height:100));scroll.hasVerticalScroller=true;scroll.drawsBackground=false
        text.isRichText=false;text.font = .systemFont(ofSize:14);text.delegate=self;text.isVerticallyResizable=true;text.autoresizingMask=[.width];text.textContainer?.widthTracksTextView=true
        text.drawsBackground=false;text.textColor = .labelColor;text.insertionPointColor = .labelColor;text.textContainerInset=NSSize(width:3,height:4)
        text.setAccessibilityLabel(zh ? "给当前任务补充指令":"Add an instruction to this task")
        text.setAccessibilityHelp(zh ? "Enter 发送，Shift+Enter 换行；草稿自动保存":"Enter to send, Shift+Enter for a new line. Drafts save automatically.")
        scroll.documentView=text;text.frame=scroll.bounds
        mode.frame=NSRect(x:10,y:23,width:280,height:26)
        mode.addItem(withTitle:zh ? "完成后发送":"Send after completion")
        if task["canSteer"] as? Bool==true {mode.addItem(withTitle:zh ? "追加到当前任务":"Steer current task");mode.selectItem(at:1)}
        mode.setAccessibilityLabel(zh ? "发送方式":"Send mode")
        status.frame=NSRect(x:14,y:5,width:332,height:16);status.font = .systemFont(ofSize:10);status.textColor = .secondaryLabelColor;status.lineBreakMode = .byTruncatingTail
        send.frame=NSRect(x:310,y:24,width:36,height:30);send.target=self;send.action=#selector(submit);send.isBordered=false
        send.image=NSImage(systemSymbolName:"arrow.up.circle.fill",accessibilityDescription:zh ? "发送":"Send")
        let cancel=CompanionActionButton(title:"",target:self,action:#selector(cancel));cancel.frame=NSRect(x:326,y:157,width:24,height:26);cancel.isBordered=false
        cancel.image=NSImage(systemSymbolName:"xmark",accessibilityDescription:zh ? "关闭输入":"Close input");cancel.setAccessibilityLabel(zh ? "关闭输入":"Close input")
        for v in [heading,pending,scroll,mode,status,send,cancel] as [NSView]{panel.contentView!.addSubview(v)}
        heading.identifier=NSUserInterfaceItemIdentifier("taskHeading")
        useSaved.title=zh ? "使用 TWOS 草稿":"Use TWOS draft";useSaved.frame=NSRect(x:10,y:23,width:280,height:26)
        useSaved.target=self;useSaved.action=#selector(discardRecovery);useSaved.isHidden=true;backdrop.addSubview(useSaved)
    }
    func load(){
        if let recovery=recovery,!restoredRecovery {
            busy=true;loading=true;render()
            recovery.load{[weak self] result in
                guard let self=self else{return}
                switch result {
                case .success(let record):
                    if let record=record {
                        self.recoveryID=record.id;self.restoredRecovery=true;self.text.string=record.text
                        self.busy=false;self.loading=false;self.dirty=true;self.revision="";self.maySubmit=false
                        (self.panel.contentView?.subviews.first{$0.identifier?.rawValue=="taskHeading"} as? NSTextField)?.stringValue=record.provider+" · "+record.title
                        self.panel.title=record.provider+" · "+record.title
                        self.status.stringValue=self.zh ? "恢复文本：请在 TWOS 核对；不会自动发送。":"Recovered text: review in TWOS; never sent automatically."
                        self.useSaved.isHidden=false;self.mode.isHidden=true;self.render();self.panel.makeFirstResponder(self.text)
                    } else{self.loadHostDraft()}
                case .failure:
                    self.busy=false;self.loading=false;self.showError("DRAFT_NOT_SAVED_RECOVERY_UNREADABLE");self.render()
                }
            };return
        }
        loadHostDraft()
    }
    func loadHostDraft(){
        var values:[String:Any]=["target":target];if let id=queueID{values["queueID"]=id}
        busy=true;loading=true;render()
        request?("draft",values){[weak self] result in
            guard let self=self else{return};self.busy=false;self.loading=false
            defer {self.releaseDismissedIfSaved()}
            if let error=result["error"] as? String{self.showError(error);self.render();return}
            self.revision=result["revision"] as? String ?? "";self.text.string=result["text"] as? String ?? "";self.dirty=false
            self.maySubmit=result["canSubmit"] as? Bool ?? true
            if self.queueID==nil {
                self.queues=result["queue"] as? [[String:String]] ?? [];self.pending.removeAllItems()
                self.pending.addItem(withTitle:self.zh ? "新补充／当前草稿":"New supplement / current draft")
                self.pending.addItems(withTitles:self.queues.enumerated().map{(self.zh ? "待发指令 ":"Pending input ")+String($0.offset+1)})
                if let mode=result["mode"] as? String{self.mode.selectItem(at:mode=="steer" && self.mode.numberOfItems>1 ? 1:0)}
                self.pending.isHidden=self.queues.isEmpty
                self.panel.contentView?.subviews.first{$0.identifier?.rawValue=="taskHeading"}?.isHidden = !self.queues.isEmpty
            }
            if self.queueID != nil {
                self.mode.selectItem(at:0)
                self.status.stringValue=self.zh ? "修改待发内容 · Enter 保存修改 · 关闭放弃修改":"Edit pending input · Enter saves the change · Close discards edits"
            } else {
                self.status.stringValue=self.maySubmit ? (self.zh ? "Enter 发送 · Shift+Enter 换行 · 自动保存":"Enter to send · Shift+Enter for a new line · Autosaved") : (self.zh ? "执行已结束 · 草稿自动保存，回 TWOS 继续":"Execution ended · Draft autosaved; continue in TWOS")
            }
            self.render();self.panel.makeFirstResponder(self.text)
        }
    }
    func showError(_ code:String){status.stringValue=CompanionControlText.error(code,zh:zh);status.toolTip=code}
    func render(){text.isEditable = !restoredRecovery && !loading && operation != "submit" && operation != "editQueue";send.isEnabled = (!busy || operation=="draft") && !revision.isEmpty && maySubmit && pendingSubmit==nil && !text.string.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty;pending.isEnabled = !busy && !dirty;mode.isEnabled=queueID==nil && !busy;send.title="";send.setAccessibilityLabel(queueID==nil ? (zh ? "发送":"Send"):(zh ? "保存待发修改":"Save queued edit"));status.toolTip=status.stringValue}
    func textView(_ textView:NSTextView,doCommandBy command:Selector)->Bool {
        if command==#selector(NSResponder.cancelOperation(_:)){cancel();return true}
        if command==#selector(NSResponder.insertNewline(_:)) {
            if textView.hasMarkedText(){return false}
            if NSApp.currentEvent?.modifierFlags.contains(.shift)==true{return false}
            submit();return true
        }
        return false
    }
    func textDidChange(_ notification:Notification){
        pendingSubmit=nil;dirty=true;render();saveTimer?.invalidate()
        if restoredRecovery{return}
        // Marked text is committed by the input method before any draft snapshot.
        saveTimer=Timer.scheduledTimer(withTimeInterval:0.8,repeats:false){[weak self] _ in guard let self=self,!self.text.hasMarkedText(),self.queueID==nil else{return};self.saveDraft()}
    }
    @objc func selectQueued(){guard !dirty else{return};let i=pending.indexOfSelectedItem;queueID=i>0 && queues.indices.contains(i-1) ? queues[i-1]["id"]:nil;revision="";load()}
    func transact(_ method:String){
        guard !restoredRecovery,!busy,!revision.isEmpty,!text.hasMarkedText(),method=="draft" || maySubmit else{return}
        guard text.string.utf8.count<=64_000 else{status.stringValue=zh ? "最多 64,000 字节；内容仍保留。":"Limit: 64,000 bytes. Your text is retained.";return}
        saveTimer?.invalidate();busy=true;operation=method;render();let sentText=text.string
        var values:[String:Any]=["target":target,"text":sentText,"revision":revision,"mode":mode.indexOfSelectedItem==1 ? "steer":"queue"]
        if let queueID=queueID{values["queueID"]=queueID}
        let completed:([String:Any])->Void = {[weak self] result in
            guard let self=self else{return};self.busy=false;self.operation=nil
            defer {self.releaseDismissedIfSaved()}
            if let error=result["error"] as? String {
                // A lost reply may follow a committed send/edit. Do not issue a
                // fresh request ID from another click before controller review.
                if method=="submit" || method=="editQueue" {self.revision="";self.dirty=true}
                if method != "draft",self.recoveryID != nil {self.showRetainedRecovery()}
                self.pendingSubmit=nil;self.showError(error);self.render();return
            }
            if let revision=result["revision"] as? String{self.revision=revision}
            if self.text.string==sentText{self.dirty=false}
            let state=result["state"] as? String ?? "unknown"
            if self.text.string==sentText,["saved","queued","edited"].contains(state){self.clearRecovery()}
            self.status.stringValue=state=="saved" ? (self.zh ? "草稿已保存":"Draft saved") : (self.zh ? "控制端回执：\(state)；不代表业务完成。":"Controller receipt: \(state). This does not mean task success.")
            self.render()
            if ["queued","edited"].contains(state){self.queueID=nil;self.revision="";self.load()}
            else if state=="sending",let receipt=result["receipt"] as? String {
                self.unconfirmedReceipt=receipt;self.revision="";self.loading=true;self.render();self.receiptGeneration+=1
                self.checkSentReceipt(receipt,generation:self.receiptGeneration,deadline:ProcessInfo.processInfo.systemUptime+4)
            }
            else if method=="draft",let submitted=self.pendingSubmit {
                self.pendingSubmit=nil
                if self.text.string==submitted {self.submit()}
            }
            else if self.dirty && self.queueID==nil {self.saveTimer=Timer.scheduledTimer(withTimeInterval:0.8,repeats:false){[weak self] _ in self?.saveDraft()}}
        }
        if let recovery=recovery {
            let record=CompanionDraftRecovery.Record(id:UUID().uuidString,target:target,title:String((task["title"] as? String ?? "").prefix(90)),provider:String((task["provider"] as? String ?? "").prefix(32)),text:sentText,uncertain:method != "draft",createdAt:Date().timeIntervalSince1970)
            recovery.save(record){[weak self] saved in
                guard let self=self else{return}
                guard saved else{completed(["error":"DRAFT_NOT_SAVED_RECOVERY_STORAGE"]);return}
                self.recoveryID=record.id
                if self.dismissed && method != "draft" {completed(["error":"CANCELLED_BEFORE_SEND_DRAFT_RETAINED"]);return}
                self.request?(method,values,completed)
            }
        } else{request?(method,values,completed)}
    }
    func checkSentReceipt(_ receipt:String,generation:Int,deadline:Double){
        guard generation==receiptGeneration else{return}
        request?("draft",["target":target,"receipt":receipt]){[weak self] result in
            guard let self=self,generation==self.receiptGeneration else{return}
            let state=result["receiptState"] as? String ?? "unknown"
            if ["accepted","running","completed"].contains(state) {self.clearRecovery();self.unconfirmedReceipt=nil;self.loading=false;self.loadHostDraft();return}
            if result["error"]==nil,["sending","queued"].contains(state),ProcessInfo.processInfo.systemUptime<deadline {
                DispatchQueue.main.asyncAfter(deadline:.now()+0.35){[weak self] in self?.checkSentReceipt(receipt,generation:generation,deadline:deadline)};return
            }
            self.loading=false;self.dirty=true;self.revision=""
            if self.recoveryID != nil {self.showRetainedRecovery()}
            self.showError(result["error"] as? String ?? "SEND_RECEIPT_UNCONFIRMED_NO_RETRY");self.render()
        }
    }
    @objc func saveDraft(){if dirty && queueID==nil{transact("draft")}}
    @objc func submit(){
        guard !text.hasMarkedText(),!text.string.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty else{return}
        if busy,operation=="draft",maySubmit {pendingSubmit=text.string;render();return}
        transact(queueID==nil ? "submit":"editQueue")
    }
    @objc func cancel(){
        dismissed=true;pendingSubmit=nil;receiptGeneration+=1;loading=false;saveTimer?.invalidate()
        if unconfirmedReceipt != nil {dirty=true}
        if dirty && queueID==nil{saveDraft()}
        // Cancel an unsent queue edit without modifying the controller's original item.
        if queueID != nil && !busy && !restoredRecovery {dirty=false;clearRecovery()}
        panel.orderOut(nil);closed?(self)
    }
    func clearRecovery(){if let id=recoveryID{recovery?.clear(id:id);recoveryID=nil}}
    func showRetainedRecovery(){
        // An uncertain/rejected mutation is never retried by reopening. The
        // explicit recovery action can reconcile after reviewing TWOS receipts.
        restoredRecovery=true;dirty=true;revision="";maySubmit=false
        pending.isHidden=true;useSaved.isHidden=false;mode.isHidden=true
    }
    @objc func discardRecovery(){
        guard restoredRecovery,let id=recoveryID else{return}
        let alert=NSAlert();alert.messageText=zh ? "丢弃这份本机恢复文本？":"Discard this local recovery text?"
        alert.informativeText=zh ? "先在 TWOS 核对投递记录并保留需要的文字。此操作不会发送或撤回任务。":"First review delivery in TWOS and keep any text you need. This does not send or undo a task."
        alert.addButton(withTitle:zh ? "保留":"Keep");alert.addButton(withTitle:zh ? "丢弃并读取 TWOS 草稿":"Discard and load TWOS draft")
        alert.beginSheetModal(for:panel){[weak self] response in
            guard let self=self,response == .alertSecondButtonReturn else{return}
            self.recovery?.clear(id:id){[weak self] saved in
                guard let self=self,saved else{return};self.recoveryID=nil;self.restoredRecovery=false;self.dirty=false
                self.useSaved.isHidden=true;self.mode.isHidden=false;self.panel.title=(self.task["provider"] as? String ?? "")+" · "+(self.task["title"] as? String ?? "")
                (self.panel.contentView?.subviews.first{$0.identifier?.rawValue=="taskHeading"} as? NSTextField)?.stringValue=self.panel.title
                self.loadHostDraft()
            }
        }
    }
    func releaseDismissedIfSaved(){
        // A close during an asynchronous autosave retains this exact editor
        // until acknowledged. Once saved, do not reopen its old task on a later
        // pencil click for another task. Unconfirmed input remains retained.
        if dismissed && !loading && !busy && !dirty {saveTimer?.invalidate();closed?(self)}
    }
    func windowShouldClose(_ sender:NSWindow)->Bool{cancel();return false}
}

extension Companion {
    @objc func editTaskFromMenu(){
        guard taskCard.append.isEnabled,let task=taskCard.task else {
            activationNotice=taskCard.append.toolTip ?? CompanionControlText.error("TASK_UNAVAILABLE_OR_READ_ONLY",zh:taskControl.language=="zh")
            panelView.setHovered(true);refreshTaskLabels();return
        }
        showTaskEditor(task)
    }
    func refreshCompanionTasks(){
        guard let selection=live.selection else{return}
        taskControl.inspect(selection:selection){[weak self] in self?.refreshTaskLabels()}
    }
    func showTaskEditor(_ task:[String:Any]){
        if let editor=taskEditor {
            editor.dismissed=false
            editor.panel.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true);editor.panel.makeFirstResponder(editor.text);writePlaybackState("task_editor_reopened");return
        }
        let editor=CompanionTaskEditor(task:task,zh:taskControl.language=="zh");taskEditor=editor
        editor.recovery=CompanionDraftRecovery(root:stateDirectory)
        let selectedHost=live.selection, generation=taskControl.generation
        editor.request={[weak self] method,values,done in guard let self=self else{done(["error":"HOST_NOT_CONNECTED"]);return};guard self.taskControl.generation==generation else{done(["error":"HOST_CONNECTION_CHANGED_DRAFT_RETAINED"]);return};self.taskControl.request(method,selection:selectedHost,values:values,completion:done)}
        editor.closed={[weak self] editor in
            // Unsaved text stays in this exact editor if the host changed or failed.
            if !editor.dirty && !editor.busy {self?.taskEditor=nil}
        }
        let safe=(taskCard.panel.screen ?? NSScreen.main)?.visibleFrame ?? panel.frame
        let size=editor.panel.frame.size
        editor.panel.setFrameOrigin(NSPoint(x:max(safe.minX,min(taskCard.panel.frame.midX-size.width/2,safe.maxX-size.width)),y:max(safe.minY,min(taskCard.panel.frame.maxY+6,safe.maxY-size.height))))
        editor.panel.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true);editor.panel.makeFirstResponder(editor.text);editor.load();writePlaybackState("task_editor_opened")
    }
    func stopCompanionTask(_ task:[String:Any],actionID:String){
        guard let target=task["target"] as? String else{return}
        taskControl.request("stop",selection:live.selection,values:["target":target]){[weak self] result in
            guard let self=self else{return}
            self.taskCard.finishStop(actionID,target:target,result:result)
            self.refreshCompanionTasks()
        }
    }
    func focusCompanionTask(_ target:String?=nil,source:String="task_card"){
        guard !hostActivationPending else{
            recordFocusMeasurement(start:ProcessInfo.processInfo.systemUptime,source:source,result:["error":"FOCUS_REQUEST_PENDING"]);return
        };hostActivationPending=true
        let start=ProcessInfo.processInfo.systemUptime
        taskControl.request("focus",selection:live.selection,values:target.map{["target":$0]} ?? [:]){[weak self] result in
            guard let self=self else{return};self.hostActivationPending=false
            if result["state"] as? String=="visible" {
                if self.stage?.isVisible==true{self.backToDesktop()}
            } else {
                self.activationNotice=CompanionControlText.error(result["error"] as? String ?? "WINDOW_FOCUS_NOT_CONFIRMED",zh:self.taskControl.language=="zh")
                self.panelView.setHovered(true)
            }
            self.recordFocusMeasurement(start:start,source:source,result:result);self.refreshTaskLabels()
        }
    }
    func recordFocusMeasurement(start:Double,source:String,result:[String:Any]){
        // Metadata only; distinguish character input from card/menu actions.
        lastFocusMeasurement=["at":Date().timeIntervalSince1970,"elapsedMs":Int((ProcessInfo.processInfo.systemUptime-start)*1000),"visibleConfirmed":result["state"] as? String=="visible","source":source]
        if let code=result["error"] as? String{lastFocusMeasurement["error"]=String(code.prefix(100))}
        focusMeasurements.append(lastFocusMeasurement)
        if focusMeasurements.count>64{focusMeasurements.removeFirst(focusMeasurements.count-64)}
        writePlaybackState("focus_receipt")
    }
}
