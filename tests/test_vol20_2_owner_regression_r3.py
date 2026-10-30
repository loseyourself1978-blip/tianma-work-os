"""R3 structural regressions: real WebKit with synthetic, non-sensitive HTML.
These are SIMULATED website tests, never evidence of a provider account/model run.
"""
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='macOS WebKit')

@pytest.fixture(scope='module')
def dom_harness(tmp_path_factory):
    root = tmp_path_factory.mktemp('r3-dom-harness')
    code = r'''
import AppKit
import WebKit
final class Probe: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
 let web: WKWebView
 let window: NSWindow
 var started = false
 init(resources: URL) {
  let config=WKWebViewConfiguration();config.websiteDataStore = .nonPersistent()
  let world=WKContentWorld.world(name:"R3 TEST ONLY")
  for name in ["provider_dom.js","handoff.js"] {
   let script=try! String(contentsOf:resources.appendingPathComponent(name)).replacingOccurrences(of:"__TWOS_ZH__",with:"false")
   config.userContentController.addUserScript(WKUserScript(source:script,injectionTime:.atDocumentEnd,forMainFrameOnly:true,in:world))
  }
  web=WKWebView(frame:NSRect(x:0,y:0,width:900,height:700),configuration:config)
  window=NSWindow(contentRect:web.frame,styleMask:[.titled],backing:.buffered,defer:false)
  super.init();config.userContentController.add(self,contentWorld:world,name:"twosHandoff")
  web.navigationDelegate=self;window.contentView=web;window.title="TEST ONLY R3 structural fixture";window.orderFront(nil)
 }
 func userContentController(_ u:WKUserContentController,didReceive m:WKScriptMessage) {
  if let v=m.body as? [String:Any],v["action"] as? String == "nativeStop" {fatalError("synthetic click acquired native Stop authority")}
 }
 func webView(_ w:WKWebView,didFinish n:WKNavigation!) {
  guard !started else{return};started=true
  let script=try! String(contentsOfFile:CommandLine.arguments[3])
  web.callAsyncJavaScript(script,arguments:[:],in:nil,in:WKContentWorld.world(name:"R3 TEST ONLY")) {result in
   switch result {case .success(let value):print(value);exit(0);case .failure(let error):fputs("\(error)\n",stderr);exit(1)}
  }
 }
}
let app=NSApplication.shared
let probe=Probe(resources:URL(fileURLWithPath:CommandLine.arguments[1]))
probe.web.load(URLRequest(url:URL(string:CommandLine.arguments[2])!))
DispatchQueue.main.asyncAfter(deadline:.now()+30){fputs("fixture timed out\n",stderr);exit(2)}
app.run()
'''
    source=root/'main.swift';source.write_text(code);binary=root/'probe'
    result=subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(root/'cache'),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=90)
    assert result.returncode == 0, result.stderr
    return binary


def test_composer_reply_cards_and_native_stop_authority(dom_harness):
    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            body=b'<!doctype html><html data-twos-fixture-provider="ChatGPT"><meta charset=utf-8><body><h1>TEST ONLY R3</h1><form><textarea id=draft></textarea></form><article data-testid=conversation-turn-1><div data-message-author-role=assistant id=answer><h2>Shapes</h2><p>A circle and a square.</p><ul><li>Round</li><li>Straight</li></ul><table><tr><td>shape</td><td>edge</td></tr></table><code>square</code><pre>code block</pre></div></article></body></html>'
            self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Page)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        result=subprocess.run([str(dom_harness),str(ROOT/'static_cockpit/native_codex'),f'http://127.0.0.1:{server.server_port}/',str(ROOT/'tests/fixtures/owner_r3_dom.js')],capture_output=True,text=True,timeout=45)
        assert result.returncode == 0, result.stdout+result.stderr
        assert 'R3_DOM_PASS' in result.stdout
    finally:server.shutdown();server.server_close();thread.join()
