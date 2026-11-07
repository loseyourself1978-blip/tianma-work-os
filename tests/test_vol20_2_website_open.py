"""Native Website sheet and navigation boundaries; synthetic pages, no model calls."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='AppKit/WebKit navigation')

@pytest.fixture(scope='module')
def website_harness(tmp_path_factory):
    root = tmp_path_factory.mktemp('website-open')
    code = (ROOT/'packaging/macos/TianmaLauncher.swift').read_text().split('// The only child runtime', 1)[0]
    for name in ['CodexAttachments.swift','CodexTelemetry.swift','NativeCodex.swift','IntegratedWorkbench.swift','PairedWorkflow.swift']:
        code += '\n' + (ROOT/'packaging/macos'/name).read_text()
    code += r'''
let app = NSApplication.shared
app.setActivationPolicy(.regular)
let mode = CommandLine.arguments[1]
let root = URL(fileURLWithPath:CommandLine.arguments[2])
if mode == "policy" {
    let good = ["https://example.test/page", "http://localhost:8765", "http://127.0.0.1:8765", "http://[::1]:8765", "http://10.0.0.1:8765", "http://172.16.0.1", "http://172.31.255.254", "http://192.168.50.20:8765"]
    for address in good { precondition(IntegratedWorkbench.validWebsite(address) != nil,address) }
    let bad = ["", "example.test", "http://example.test", "http://8.8.8.8", "http://172.15.0.1", "http://172.32.0.1", "http://192.169.0.1", "http://192.168.1.1.evil.test", "http://192.168.1.999", "http://192.168.01.2", "http://10.1", "http://user:pass@192.168.1.1", "javascript:alert(1)", "file:///tmp/private", "https://example.test/?token=private", "https://example.test/#private"]
    for address in bad { precondition(IntegratedWorkbench.validWebsite(address) == nil,address); precondition(!IntegratedWorkbench.websiteInputError(address).isEmpty) }
    let selected = URL(string:"http://192.168.50.20:8765")!
    for path in ["/", "/page", "/assets/style.css", "/api/data?offset=1"] {
        precondition(NativeWorkbench.permitsNavigation(URL(string:selected.absoluteString+path)!,serviceHome:selected,isSubframe:false))
        precondition(NativeWorkbench.permitsNavigation(URL(string:selected.absoluteString+path)!,serviceHome:selected,isSubframe:true))
    }
    for address in ["http://192.168.50.21:8765", "http://192.168.50.20:8766", "http://localhost:8765", "http://example.test", "http://user:pass@192.168.50.20:8765", "file:///tmp/private", "javascript:alert(1)"] {
        for frame in [true,false] { precondition(!NativeWorkbench.permitsNavigation(URL(string:address)!,serviceHome:selected,isSubframe:frame),address) }
    }
    precondition(!NativeWorkbench.permitsNavigation(selected,serviceHome:URL(string:"https://chatgpt.com")!,isSubframe:false))
    precondition(NativeWorkbench.permitsNavigation(URL(string:"https://example.test")!,serviceHome:selected,isSubframe:false))
    precondition(NativeWorkbench.displayOrigin(selected) == "http://192.168.50.20:8765")
    precondition(NativeWorkbench.displayOrigin(URL(string:"http://[::1]:8765/page")!) == "http://[::1]:8765")
    print("WEBSITE_POLICY_PASS");exit(0)
}
let base = URL(string:CommandLine.arguments[3])!
try! NativeWorkbench.save(["kind0":"Website…","kind1":"Website…","url0":base.absoluteString,"url1":base.absoluteString],at:root.appendingPathComponent("paired-workbench.json"))
let work = IntegratedWorkbench(preferences:root,resources:nil,translate:{$0},openProjects:{fatalError("project side effect")})
work.start()
let initial = [work.webPanes[0]!,work.webPanes[1]!]
let originalRevision = work.routeRevision
var phase = 0, ticks = 0
func prompt(_ side:Int,_ text:String) -> WebsiteAddressPrompt {
    let picker = side == 0 ? work.leftPicker : work.rightPicker
    picker.selectItem(at:work.options.firstIndex(of:"Website…")!);work.changePane(picker)
    precondition(work.websitePrompt != nil)
    let sheet = work.websitePrompt!;sheet.field.stringValue = text
    return sheet
}
func noSideEffects() {
    precondition(work.codex == nil && work.webTransfers.isEmpty && work.dialogue == nil && work.webFileSelections.isEmpty)
}
let timer = Timer(timeInterval:0.05,repeats:true) { _ in
    ticks += 1;precondition(ticks < 400,"native website test deadline, phase \(phase)")
    noSideEffects()
    switch phase {
    case 0:
        guard initial.allSatisfy({$0.web.url == base && !$0.web.isLoading}) else{return}
        precondition(initial[0] !== initial[1])
        let sheet=prompt(0,"http://public.example.test")
        sheet.alert.buttons[0].performClick(nil)
        precondition(work.websitePrompt === sheet && !sheet.errorLabel.isHidden)
        precondition(sheet.field.stringValue == "http://public.example.test")
        precondition(sheet.alert.window.sheetParent === work.window)
        precondition(work.routeRevision == originalRevision && work.webPanes[0] === initial[0])
        sheet.alert.buttons[1].performClick(nil)
        // Cancel completion is asynchronous. Test the other side next tick.
        phase=1
    case 1:
        guard work.websitePrompt == nil else{return}
        let sheet=prompt(1,"file:///tmp/private")
        sheet.alert.buttons[0].performClick(nil)
        precondition(!sheet.errorLabel.isHidden && work.routeRevision == originalRevision)
        sheet.alert.buttons[1].performClick(nil);phase=2
    case 2:
        guard work.websitePrompt == nil else{return}
        precondition(work.routeRevision == originalRevision && work.webPanes[0] === initial[0] && work.webPanes[1] === initial[1])
        // A previous saved location on this host must not override this explicit URL.
        try! NativeWorkbench.save(["url":base.appendingPathComponent("stale").absoluteString],at:root.appendingPathComponent("paired-location-0-127.0.0.1.json"))
        let sheet=prompt(0,base.appendingPathComponent("left").absoluteString)
        sheet.alert.buttons[0].performClick(nil);sheet.alert.buttons[0].performClick(nil);phase=3
    case 3:
        guard work.websitePrompt == nil,work.webPanes[0]!.web.url == base.appendingPathComponent("left"),!work.webPanes[0]!.web.isLoading else{return}
        precondition(work.webPanes[1] === initial[1] && initial[1].web.url == base)
        let sheet=prompt(1,base.appendingPathComponent("right").absoluteString)
        sheet.alert.buttons[0].performClick(nil);phase=4
    case 4:
        guard work.websitePrompt == nil,work.webPanes[1]!.web.url == base.appendingPathComponent("right"),!work.webPanes[1]!.web.isLoading else{return}
        precondition(work.webPanes[0]!.web.url == base.appendingPathComponent("left"))
        let old=work.webPanes[0]!
        old.navigationFailed(NSError(domain:NSURLErrorDomain,code:NSURLErrorCannotConnectToHost))
        precondition(!old.notice.isHidden && old.notice.stringValue.contains("This webpage could not finish loading"))
        old.web.load(URLRequest(url:base.appendingPathComponent("stale")));phase=5
    case 5:
        guard work.webPanes[0]!.web.url == base.appendingPathComponent("stale"),!work.webPanes[0]!.web.isLoading else{return}
        precondition(work.webPanes[0]!.notice.isHidden && work.webPanes[0]!.notice.stringValue.isEmpty,"successful recovery must clear the network error")
        let sheet=prompt(0,base.appendingPathComponent("left").absoluteString)
        sheet.alert.buttons[0].performClick(nil);phase=6
    case 6:
        guard work.websitePrompt == nil,work.webPanes[0]!.web.url == base.appendingPathComponent("left"),!work.webPanes[0]!.web.isLoading else{return}
        let saved=try! JSONSerialization.jsonObject(with:Data(contentsOf:root.appendingPathComponent("paired-workbench.json"))) as! [String:String]
        precondition(saved["url0"] == base.appendingPathComponent("left").absoluteString && saved["url1"] == base.appendingPathComponent("right").absoluteString)
        precondition(work.webPanes[0]!.web.configuration.userContentController.userScripts.isEmpty)
        print("WEBSITE_NATIVE_SHEET_AND_WEBKIT_PASS");fflush(stdout);app.terminate(nil)
    default:break
    }
}
RunLoop.main.add(timer,forMode:.common)
app.run()
'''
    source=root/'main.swift';source.write_text(code);binary=root/'website-component'
    build=subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(root/'cache'),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=150)
    assert build.returncode == 0,build.stderr
    return binary


def test_explicit_private_dashboard_origin_and_rejection_boundaries(website_harness,tmp_path):
    result=subprocess.run([str(website_harness),'policy',str(tmp_path/'profile')],capture_output=True,text=True,timeout=20)
    assert result.returncode == 0,result.stderr
    assert 'WEBSITE_POLICY_PASS' in result.stdout


def test_actual_native_sheet_retains_errors_cancels_and_opens_both_webviews(website_harness,tmp_path):
    requests=[]
    class Fixture(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body=b'<!doctype html><title>TEST ONLY Website navigation</title><p>Non-sensitive navigation fixture</p>'
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        result=subprocess.run([str(website_harness),'sheet',str(tmp_path/'profile'),f'http://127.0.0.1:{server.server_port}/'],capture_output=True,text=True,timeout=40)
        assert result.returncode == 0,result.stderr
        assert 'WEBSITE_NATIVE_SHEET_AND_WEBKIT_PASS' in result.stdout
        assert requests.count('/left') == 2,requests  # Explicit same-page reopen is intentional.
        assert requests.count('/right') == 1,requests  # Double Open must not duplicate navigation.
    finally:server.shutdown();server.server_close();thread.join()
