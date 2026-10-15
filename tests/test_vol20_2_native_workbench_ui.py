"""Real WebKit single-window integration against a local synthetic website only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
pytestmark=pytest.mark.skipif(sys.platform!='darwin',reason='macOS WebKit integration')

@pytest.fixture(scope='module')
def integrated_harness(tmp_path_factory):
    root=tmp_path_factory.mktemp('integrated-webkit')
    code=(ROOT/'packaging/macos/TianmaLauncher.swift').read_text().split('// The only child runtime',1)[0]
    code+='\n'+(ROOT/'packaging/macos/NativeCodex.swift').read_text()+'\n'+(ROOT/'packaging/macos/IntegratedWorkbench.swift').read_text()
    code+=r'''
let app = NSApplication.shared
let root = URL(fileURLWithPath:CommandLine.arguments[1])
let base = URL(string:CommandLine.arguments[2])!
let resources = URL(fileURLWithPath:CommandLine.arguments[3])
try NativeWorkbench.save(["kind0":"Website…","kind1":"Codex","url0":base.absoluteString,"url1":""],at:root.appendingPathComponent("paired-workbench.json"))
let workbench = IntegratedWorkbench(preferences:root, resources:resources, translate:{$0}, openProjects:{fatalError("legacy was launched")})
workbench.start()
let browser = workbench.webPanes[0]!
let client = workbench.codex!
var polls = 0
func ready() {
    polls += 1
    if client.pageReady && !browser.web.isLoading && browser.web.url == base {
        precondition(browser.web.window === workbench.window && client.web.window === workbench.window,"both actual contexts must be inside the same native window")
        precondition(workbench.split.arrangedSubviews.allSatisfy{$0.bounds.width > 400})
        browser.web.evaluateJavaScript(NativeWorkbench.handoffScript(allowLatestReply:true)) { value, error in
            precondition(error == nil && value as? String == "Latest official answer", "current and legacy site markers must return only the last visible answer")
        browser.web.evaluateJavaScript(NativeWorkbench.handoffScript(allowLatestReply:false)) { value, error in
            precondition(error == nil && value as? String == "", "other websites require an explicit selection")
        browser.web.evaluateJavaScript("document.getElementById('draft').value='Existing draft'; document.getElementById('answer').textContent='One instruction'; const range=document.createRange(); range.selectNodeContents(document.getElementById('answer'));getSelection().removeAllRanges();getSelection().addRange(range);") { _, error in
            precondition(error == nil)
            browser.handoff()
            DispatchQueue.main.asyncAfter(deadline:.now()+0.2) {
                precondition(client.draftText == "One instruction" && client.sourceURL == base,"selection must arrive in the paired composer without a clipboard or send")
                browser.placeDraft("Returned result",expectedSource:base) { ok in
                    precondition(ok)
                    browser.web.evaluateJavaScript("JSON.stringify({text:document.getElementById('draft').value,sends:window.sends})") { value, error in
                        precondition(error == nil)
                        let state = try! JSONSerialization.jsonObject(with:(value as! String).data(using:.utf8)!) as! [String:Any]
                        precondition(state["text"] as? String == "Existing draft\n\nReturned result" && state["sends"] as? Int == 0,"return must preserve the draft without submitting")
                        browser.placeDraft("Wrong discussion",expectedSource:base.appendingPathComponent("other")) { allowed in
                            precondition(!allowed)
                            runRenderer()
                        }
                    }
                }
            }
        }
        }
        }
    } else if polls < 150 {
        DispatchQueue.main.asyncAfter(deadline:.now()+0.1){ready()}
    } else { fatalError("actual WebKit pages did not load") }
}
func runRenderer() {
    let script = #"""
    (()=>{
      const $=id=>document.getElementById(id),r=(kind,payload)=>window.twosReceive({kind,payload});
      const checks=[];const assert=(value,label)=>{if(!value)throw Error(label);checks.push(label)};
      r('locale',{zh:true});r('models',{items:[{model:'model-a',displayName:'Model A'},{model:'model-b',displayName:'Model B'}]});
      r('thread',{thread:{id:'fixture-thread',cwd:'/synthetic/workspace'}});
      r('control',{connected:true,busy:true,desktopRunning:false,historyReady:true,threadId:'fixture-thread'});
      r('event',{method:'item/reasoning/summaryTextDelta',params:{itemId:'thinking',summaryIndex:0,delta:'Public summary'}});
      assert($('item-thinking').querySelector('details').open,'thinking summary readable during execution');
      $('item-thinking').querySelector('details').open=false;
      r('event',{method:'item/reasoning/summaryTextDelta',params:{itemId:'thinking',summaryIndex:0,delta:' update'}});
      assert(!$('item-thinking').querySelector('details').open,'collapse persists through stream updates');
      r('event',{method:'item/completed',params:{item:{id:'response',type:'agentMessage',phase:'final_answer',text:'### Result\n**Ready**\n<script>unsafe</script>'}}});
      assert($('item-response').querySelector('h3').textContent==='Result'&&!$('item-response').querySelector('script'),'safe markdown display');
      const command='node -e '+ 'x'.repeat(300);
      r('event',{method:'item/completed',params:{item:{id:'command',type:'commandExecution',command,exitCode:0,aggregatedOutput:'PASS'}}});
      assert($('item-command').querySelector('summary').textContent.length<=111&&$('item-command').querySelector('pre').textContent===command,'long commands stay compact with complete details');
      r('notice',{text:'Reply failed',code:-1,detail:'Synthetic provider failure'});
      assert(!$('notice-details').hidden&&$('notice-detail').textContent==='Synthetic provider failure','empty failure exposes actual cause and visible details');
      $('notice-details').open=true;
      r('notice',{text:'Reply failed',detail:'Second diagnostic'});
      assert($('notice-details').open,'error details remain expanded');
      r('turnCompleted',{status:'completed'});assert($('notice').hidden,'successful completion clears a recovered transient error');
      r('result',{available:true,source:'https://example.invalid/c/source'});
      assert(!$('return').hidden,'verified completed result has return action');
      r('control',{connected:true,busy:false,uncertain:true,historyReady:true,threadId:'fixture-thread'});
      $('draft').value='Do not repeat';$('draft').dispatchEvent(new Event('input'));
      assert($('send').disabled&&!$('reconnect').hidden,'unknown execution blocks resubmit and has recovery action');
      assert($('model').tagName==='SELECT'&&$('model').options.length===3,'models use native selectable dropdown');
      assert(document.documentElement.scrollWidth<=innerWidth+2,'no horizontal viewport overflow');
      return checks;
    })()
    """#
    client.web.evaluateJavaScript(script) { value, error in
        precondition(error == nil,"renderer: \(String(describing:error))")
        precondition((value as? [String])?.count == 11)
        // Switching positions retains the very same native Codex connection.
        let instance=workbench.codex
        workbench.leftPicker.selectItem(at:1);workbench.changePane(workbench.leftPicker)
        precondition(workbench.codex === instance && workbench.codex!.web.window === workbench.window)
        precondition(workbench.kinds == ["Codex","Website…"] && workbench.webPanes[1] === browser, "moving panes must keep the original browser context")
        let movedLocation = root.appendingPathComponent("paired-location-1-127.0.0.1.json")
        let saved = try! JSONSerialization.jsonObject(with:Data(contentsOf:movedLocation)) as! [String:String]
        precondition(saved["url"] == base.absoluteString && browser.locationKey == movedLocation.lastPathComponent, "restart must restore the moved discussion at its new position")
        precondition(workbench.webCache["0:\(base.absoluteString)"] == nil, "moving a browser must remove the stale cache alias")
        workbench.kinds[0]="Website…";workbench.urls[0]=base.absoluteString;workbench.rebuild(0)
        precondition(workbench.webPanes[0] !== browser && workbench.webPanes[1] === browser && browser.web.window === workbench.window, "two website panes must own independent views, never steal each other's context")
        print("ONE_WINDOW_HANDOFF_RETURN_UI_PASS");fflush(stdout);app.terminate(nil)
    }
}
DispatchQueue.main.asyncAfter(deadline:.now()+0.1){ready()}
app.run()
'''
    source=root/'main.swift';source.write_text(code);binary=root/'integrated-component'
    done=subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(root/'cache'),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120)
    assert done.returncode==0,done.stderr
    return binary


def test_real_single_window_handoff_return_and_streaming_ui(integrated_harness,tmp_path):
    class Fixture(BaseHTTPRequestHandler):
        def do_GET(self):
            body=b'<!doctype html><meta charset="utf-8"><div data-message-author-role="assistant">Earlier official answer</div><div data-markdown-text-style="reasoning-summary">Public summary</div><div data-markdown-text-style="assistant-message">Latest official answer</div><div data-markdown-text-style="assistant-message" style="display:none">Hidden variant</div><p id="answer">Fixture instruction</p><form onsubmit="window.sends++;return false"><textarea id="draft"></textarea><button>Send</button></form><script>window.sends=0</script>'
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        result=subprocess.run([str(integrated_harness),str(tmp_path/'prefs'),f'http://127.0.0.1:{server.server_port}/',str(ROOT/'static_cockpit')],capture_output=True,text=True,timeout=40)
        assert result.returncode==0,result.stderr
        assert 'ONE_WINDOW_HANDOFF_RETURN_UI_PASS' in result.stdout
    finally:server.shutdown();server.server_close();thread.join()
