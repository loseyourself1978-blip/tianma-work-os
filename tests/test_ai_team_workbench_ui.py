"""Real AppKit/WKWebView navigation, offline and without provider accounts."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS workbench")
def test_team_toolbar_roster_and_language_preserve_draft(tmp_path):
    mac = ROOT / "packaging/macos"
    swift = (mac / "TianmaLauncher.swift").read_text().split("// The only child runtime", 1)[0]
    for name in ("CodexAttachments","CodexTelemetry","NativeCodex","TeamReport","TeamRun","TeamWorkspace","IntegratedWorkbench","PairedWorkflow"):
        body = (mac / (name+".swift")).read_text()
        if name == "TeamWorkspace":
            # Only the externally authenticated endpoints are disabled. The
            # toolbar, page, bridge and draft behavior all use product code.
            assert body.count("connectTeamChannels()") == 2
            body = re.sub(r"(?m)^\s*connectTeamChannels\(\)\s*$", "", body)
            assert body.count("connectTeamChannels()") == 1
            navigation = "w.start(embedded: true, navigateTo: URL(string: home))"
            assert body.count(navigation) == 1
            body = body.replace(navigation, "_ = home")
            # Start the actual native folder sheet at a populated fixture. The
            # picker completion, validation and UI publication use product code.
            insert = "    panel.beginSheetModal(for: win)"
            assert body.count(insert) == 1
            body = body.replace(insert, """
    if let fixture = ProcessInfo.processInfo.environment["TWOS_TEST_EXISTING_FOLDER"] {
      panel.directoryURL = URL(fileURLWithPath:fixture, isDirectory:true)
      panel.prompt = "Use fixture folder"
      func pressFolderButton() {
        guard panel.isVisible else { return }
        func attribute(_ element:AXUIElement,_ name:String)->CFTypeRef? {
          var value:CFTypeRef?
          AXUIElementCopyAttributeValue(element,name as CFString,&value)
          return value
        }
        func press(_ element:AXUIElement,_ depth:Int)->Bool {
          guard depth < 22, let role = attribute(element,"AXRole") as? String,
                !["AXWebArea","AXTable","AXBrowser","AXOutline","AXList"].contains(role) else { return false }
          if role=="AXButton", attribute(element,"AXTitle") as? String=="Use fixture folder",
             attribute(element,"AXEnabled") as? Bool==true {
            return AXUIElementPerformAction(element,kAXPressAction as CFString) == .success
          }
          return (attribute(element,"AXChildren") as? [AXUIElement] ?? []).contains { press($0,depth+1) }
        }
        if !press(AXUIElementCreateApplication(getpid()),0) {
          DispatchQueue.main.asyncAfter(deadline:.now()+0.2) { pressFolderButton() }
        }
      }
      DispatchQueue.main.asyncAfter(deadline:.now()+1) { pressFolderButton() }
    }
""" + insert)
        swift += "\n" + body
    swift += r'''
let app=NSApplication.shared
let root=URL(fileURLWithPath:CommandLine.arguments[1]), resources=URL(fileURLWithPath:CommandLine.arguments[2])
try NativeWorkbench.safeDirectory(root)
try NativeWorkbench.save(["kind0":"Website…","kind1":"Website…","url0":"http://127.0.0.1:1/","url1":"http://127.0.0.1:1/"],at:root.appendingPathComponent("paired-workbench.json"))
let recovering=CommandLine.arguments.contains("--recover")
var operation=""
var snapshot:URL?
if recovering {
    let directory=root.appendingPathComponent("team-r1")
    try NativeWorkbench.safeDirectory(directory)
    let workspace=root.appendingPathComponent("synthetic-work")
    try NativeWorkbench.safeDirectory(workspace)
    try Data("existing".utf8).write(to:workspace.appendingPathComponent("keep.txt"))
    let f=try NativeCodex.inspectDirectory(workspace.path,isolated:true)
    let roles=[TeamMember(role:"Planner",product:"Codex",provider:"OpenAI",model:"fixture-P"),
               TeamMember(role:"Builder",product:"Codex",provider:"OpenAI",model:"fixture-B"),
               TeamMember(role:"Reviewer",product:"Claude web",provider:"Anthropic",model:"fixture-R")]
    var r=try TeamRun.create(goal:"Synthetic recovery check",csv:TeamFiles.sample,folder:f,members:roles)
    var archived=try TeamRun.create(goal:"Previous sales <archive>",csv:TeamFiles.sample,folder:f,members:roles)
    let sent=try archived.begin(archived.prompt())
    let body = try TeamFiles.json(TeamPlan(builder:TeamText(en:"Calculate totals",zh:"计算合计"),reviewer:TeamText(en:"Check every figure",zh:"核对数字"),acceptance:TeamText(en:"Counts match",zh:"笔数相符")))
    try archived.receive(id:sent.id,text:body,actual:"fixture-P",source:"fixture",thread:"isolated-plan",turn:"fixture-turn")
    archived.state="stopped"
    try TeamFiles.bytes(archived).write(to:directory.appendingPathComponent(archived.id+".json"))
    operation=try r.begin(r.prompt()).id
    snapshot=directory.appendingPathComponent(r.id+".json")
    try TeamFiles.bytes(r).write(to:snapshot!)
    try Data(r.id.utf8).write(to:directory.appendingPathComponent("current"))
}
let importing=CommandLine.arguments.contains("--import")
let teamDir=root.appendingPathComponent("team-r1")
var importedID=""
var inputRecords:[URL:Data]=[:]
if importing {
    let support=root.deletingLastPathComponent()
    let path=try NativeCodex.inspectDirectory(root.path,isolated:true)
    let roles=[TeamMember(role:"Planner",product:"Codex",provider:"OpenAI",model:"P"),
               TeamMember(role:"Builder",product:"Codex",provider:"OpenAI",model:"B"),
               TeamMember(role:"Reviewer",product:"Claude",provider:"Anthropic",model:"R")]
    var recent=try TeamRun.create(goal:"Imported engineering chat",csv:TeamFiles.sample,folder:path,members:roles)
    let oldOnly=try TeamRun.create(goal:"Preview only",csv:TeamFiles.sample,folder:path,members:roles)
    importedID=recent.id
    for (profile,comment) in [("TWOS AI Team Acceptance","latest"),("TWOS AI Team R1 Preview","earlier")] {
        let input=support.appendingPathComponent(profile).appendingPathComponent("team-r1")
        try FileManager.default.createDirectory(at:input,withIntermediateDirectories:true)
        recent.comment=comment
        let record=input.appendingPathComponent(recent.id+".json")
        inputRecords[record]=try TeamFiles.bytes(recent)
        try inputRecords[record]!.write(to:record)
        try Data(recent.id.utf8).write(to:input.appendingPathComponent("current"))
        if comment=="earlier" {
            try TeamFiles.bytes(oldOnly).write(to:input.appendingPathComponent(oldOnly.id+".json"))
        }
    }
}
var chinese=false
let w=IntegratedWorkbench(preferences:root,resources:resources,translate:{chinese && $0=="Back" ? "后退" : $0},openProjects:{})
w.showWindow(nil)
let left=w.webPanes[0], right=w.webPanes[1]
w.toggleTeam()
let panel=w.teamPanel!
func check(_ script:String, _ next:@escaping()->Void){
    panel.web.evaluateJavaScript("{"+script+"}"){value,error in
        guard error==nil, value as? Bool == true else {print("FAILED",script,(error as NSError?)?.userInfo["WKJavaScriptExceptionMessage"] ?? "",String(describing:value));exit(1)}
        next()
    }
}
func waitFor(_ script:String, _ next:@escaping()->Void){
    panel.web.evaluateJavaScript(script){v,_ in
        if v as? Bool==true {next()}
        else {DispatchQueue.main.asyncAfter(deadline:.now()+0.08){waitFor(script,next)}}
    }
}
if importing {
    let clickImport="const b=[...document.querySelectorAll('#library button')].find(b=>b.textContent==='Load earlier preview chats');b.click();true"
    waitFor("[...document.querySelectorAll('#library button')].some(b=>b.textContent==='Load earlier preview chats' && !b.disabled)") {
        check(clickImport) {
            waitFor("document.querySelectorAll('#rooms .room').length===2 && !state.loadingHistory") {
                let path=teamDir.appendingPathComponent(importedID+".json")
                var saved=try! JSONDecoder().decode(TeamRun.self,from:Data(contentsOf:path))
                precondition(saved.comment=="latest")
                saved.comment="retained local value"
                try! TeamFiles.bytes(saved).write(to:path,options:.atomic)
                check(clickImport) {
                    waitFor("!state.loadingHistory && state.notice==='archiveLoaded'") {
                        let final=try! JSONDecoder().decode(TeamRun.self,from:Data(contentsOf:path))
                        precondition(final.comment=="retained local value")
                        precondition(!FileManager.default.fileExists(atPath:teamDir.appendingPathComponent("current").path))
                        for (url,bytes) in inputRecords { precondition((try? Data(contentsOf:url))==bytes) }
                        check("[...document.querySelectorAll('#rooms .room')].find(b=>b.textContent.includes('Imported engineering chat')).click();true"){
                            waitFor("state.archived && !state.current && document.querySelector('#work h2')?.textContent==='Imported engineering chat'"){
                                print("PASS acceptance and preview import, duplicate precedence, read-only browsing and no current dispatch");exit(0)
                            }
                        }
                    }
                }
            }
        }
    }
} else if recovering {
    waitFor("document.querySelector('#run-status')?.textContent==='Paused'"){
        let stored=try! JSONDecoder().decode(TeamRun.self,from:Data(contentsOf:snapshot!))
        precondition(stored.pending?.id==operation && stored.reason=="restart")
        check("if(!document.querySelector('#library #new-task').disabled)throw Error('active run was replaceable');const stop=[...document.querySelectorAll('#work button')].find(b=>b.textContent==='Stop dispatches');stop.click();true"){
            waitFor("document.querySelector('#run-status')?.textContent==='Future dispatches have stopped.'"){
                let stopped=try! JSONDecoder().decode(TeamRun.self,from:Data(contentsOf:snapshot!))
                precondition(stopped.stopRequested==true && stopped.state=="stopped" && stopped.pending==nil)
                precondition(stopped.attempts.count==1 && stopped.attempts[0].id==operation && stopped.attempts[0].state=="cancelled" && stopped.attempts[0].thread==nil)
                check("const input=document.getElementById('team-message');input.value='Saved note 你好';input.dispatchEvent(new Event('input'));[...document.querySelectorAll('#work button')].find(b=>b.textContent==='Save note').click();true"){
                  waitFor("document.querySelector('.feed').textContent.includes('Saved note 你好')"){
                    check("const search=document.getElementById('search');search.value='Previous sales';search.dispatchEvent(new Event('input'));const rooms=document.querySelectorAll('#rooms .room');if(rooms.length===1)rooms[0].click();rooms.length===1"){
                      waitFor("document.querySelector('#work h2')?.textContent==='Previous sales <archive>'"){
                        check("const msg=[...document.querySelectorAll('.entry')].find(b=>b.textContent.includes('Calculate totals'));msg.click();document.querySelector('#scope-info').textContent.includes('Check every figure') && document.querySelector('#scope-info').textContent.includes('fixture-turn') && document.querySelector('#delivery-files').textContent.includes('Chosen destination') && memberStatus({state:'completed',dispatch:'running',service:'Codex'})==='Completed' && !document.querySelector('#team-message')"){
                          check("[...document.querySelectorAll('#nav button')].find(b=>b.textContent==='Current task').click();true"){
                            waitFor("document.querySelector('.feed')?.textContent.includes('Saved note 你好')"){
                              check("const b=document.querySelector('#library #new-task');if(b.disabled || b.textContent!=='New task')throw Error('sidebar action missing');b.click();true"){
                                waitFor("document.querySelector('#work h2')?.textContent==='New team task'"){
                                  precondition(!FileManager.default.fileExists(atPath:root.appendingPathComponent("team-r1/current").path))
                                  precondition(FileManager.default.fileExists(atPath:snapshot!.path))
                                  print("PASS stop, persisted history, sidebar new task and previous record intact");exit(0)
                                }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
            }
        }
    }
} else {
waitFor("document.querySelector('#work h2')?.textContent==='New team task'"){
    check("[...document.querySelectorAll('#work button')].find(b=>b.textContent==='Choose delivery folder…').click();true"){
      waitFor("document.querySelector('#work').innerText.includes('/delivery-with-existing')"){
    check("if(!document.querySelector('#library #new-task') || document.querySelector('#nav #new-task'))throw Error('new task placement');const g=document.getElementById('goal');g.value='Keep my goal';g.dispatchEvent(new Event('input'));document.querySelector('#work .primary').click();document.body.innerText.includes('Your team') && document.body.innerText.includes('Builder') && [...document.querySelectorAll('#work select[id$=provider]')].every(s=>s.options.length===4) && document.querySelectorAll('#work select[id$=provider]').length===3 && document.querySelector('#work .primary').disabled"){
        check("const menus=['planner','builder','reviewer'];['DeepSeek','Claude','Codex'].forEach((v,i)=>{const s=document.getElementById(menus[i]+'-provider');s.value=v;s.dispatchEvent(new Event('change'))});true"){
          waitFor("document.querySelector('#planner-provider')?.value==='DeepSeek' && document.querySelector('#builder-provider')?.value==='Claude' && document.querySelector('#reviewer-model')!==null"){
        w.toggleTeam();precondition(!w.split.isHidden && w.webPanes[0]===left && w.webPanes[1]===right)
        chinese=true;w.refreshLanguage();w.toggleTeam();precondition(w.split.isHidden && w.teamButton.title=="返回双栏工作台")
        waitFor("document.querySelector('#work h2')?.textContent==='本次团队'"){
            check("[...document.querySelectorAll('#work button')].find(b=>b.textContent==='调整成员或目标').click();document.getElementById('goal').value==='Keep my goal' && document.documentElement.lang==='zh-CN' && document.body.innerText.includes('独立审核者')"){
                print("PASS bilingual editable providers / missing-channel guard / same panes / retained goal");exit(0)
            }
        }
    }
}
}
}
}
}
}
DispatchQueue.main.asyncAfter(deadline:.now()+25){print("UI timeout");exit(2)}
app.run()
'''
    main = tmp_path / "main.swift"
    main.write_text(swift)
    binary = tmp_path / "team-ui"
    subprocess.run(["xcrun","swiftc","-swift-version","5","-module-cache-path",str(tmp_path/"cache"),str(main),"-o",str(binary)],check=True,timeout=180)
    delivery = tmp_path / "delivery-with-existing"
    delivery.mkdir()
    sentinel = delivery / "keep.txt"
    sentinel.write_text("Keep this file.")
    for mode in ("navigate", "recover", "import"):
        profile = tmp_path / ("Tianma Work OS Preferences" if mode == "import" else mode)
        result = subprocess.run(
            [str(binary), str(profile), str(ROOT / "static_cockpit"), "--" + mode],
            capture_output=True, text=True, timeout=42, env={**os.environ, "TWOS_TEST_EXISTING_FOLDER": str(delivery)},
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert sentinel.read_text() == "Keep this file."


def test_group_message_uses_the_bound_live_transport_state():
    app_js = ROOT / "static_cockpit/ai_team/app.js"
    probe = """
      globalThis.window = {};
      const fs = require('node:fs'), vm = require('node:vm');
      const ui = vm.createContext({window, console, document: {}, crypto: {}});
      vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),ui);
      vm.runInContext(`state={zh:false,archived:false,run:{state:'running'},codex:'connected'};
        const attempt={state:'intent',service:'Codex',dispatch:'running'};
        if(memberStatus(attempt)!=='Running')throw Error('active turn');
        attempt.dispatch='completed';
        if(memberStatus(attempt)!=='Checking the returned result')throw Error('reconciliation');
        state.codex='disconnected';
        if(memberStatus(attempt)!=='Current status unavailable')throw Error('stale transport');
        state.archived=true;attempt.state='completed';
        if(memberStatus(attempt)!=='Completed')throw Error('archived history');`,ui);
    """
    subprocess.run(["node", "-e", probe, str(app_js)], check=True, timeout=10)
