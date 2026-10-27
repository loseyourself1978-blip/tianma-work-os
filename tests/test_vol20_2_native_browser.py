"""Native browser boundary/persistence tests. No Owner profile or real model calls."""
from pathlib import Path
import json
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'packaging/macos/TianmaLauncher.swift'
pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='Native macOS WebKit component')

@pytest.fixture(scope='module')
def harness(tmp_path_factory):
    root = tmp_path_factory.mktemp('native-browser-10137')
    production = NATIVE.read_text().split('// The only child runtime', 1)[0]
    source = root / 'main.swift'
    source.write_text(production + r'''
let app = NSApplication.shared
let mode = CommandLine.arguments[1]
let root = URL(fileURLWithPath: CommandLine.arguments[2])
if mode == "boundary" {
    let remote = URL(string:"https://claude.ai/")!, local = URL(string:"http://127.0.0.1:9876/")!
    precondition(NativeWorkbench.permitsNavigation(URL(string:"about:srcdoc")!,serviceHome:remote,isSubframe:true))
    precondition(!NativeWorkbench.permitsNavigation(URL(string:"about:srcdoc")!,serviceHome:remote,isSubframe:false))
    for blocked in ["about:srcdoc?privileged", "about:srcdoc#fragment", "about:settings", "file:///tmp/private", "javascript:alert(1)", "twos-nyra://visibility/show", "http://claude.ai/"] {
        precondition(!NativeWorkbench.permitsNavigation(URL(string:blocked)!,serviceHome:remote,isSubframe:true),blocked)
    }
    precondition(NativeWorkbench.permitsNavigation(URL(string:"https://challenges.cloudflare.com/")!,serviceHome:remote,isSubframe:true))
    precondition(NativeWorkbench.permitsNavigation(local.appendingPathComponent("test"),serviceHome:local,isSubframe:false))
    precondition(!NativeWorkbench.permitsNavigation(URL(string:"http://127.0.0.1:9877/")!,serviceHome:local,isSubframe:true))
    for url in ["http://chatgpt.com/c/abc", "https://chatgpt.com.evil.test/c/abc", "https://evil.test/c/abc", "file:///tmp/abc", "https://chatgpt.com/auth/callback?code=private", "https://chatgpt.com/api/auth", "https://user:pass@chatgpt.com/c/abc", "https://chatgpt.com:444/c/abc"] {
        precondition(NativeWorkbench.restorableURL(URL(string:url)) == nil, url)
    }
    precondition(NativeWorkbench.restorableURL(URL(string:"https://chatgpt.com/c/abc-def?code=private#token"))!.absoluteString == "https://chatgpt.com/c/abc-def")
    precondition(NativeWorkbench.restorableURL(URL(string:"https://chatgpt.com/g/g-test/project"))!.absoluteString == "https://chatgpt.com/g/g-test/project")
    try NativeWorkbench.save(["url":"https://chatgpt.com/c/synthetic"], at: root.appendingPathComponent("saved.json"))
    let attributes = try FileManager.default.attributesOfItem(atPath:root.appendingPathComponent("saved.json").path)
    precondition((attributes[.posixPermissions] as! NSNumber).intValue == 0o600)
    let link = root.appendingPathComponent("link")
    try FileManager.default.createSymbolicLink(at:link, withDestinationURL:root)
    do {try NativeWorkbench.safeDirectory(link.appendingPathComponent("child")); fatalError("symlink accepted")}
    catch {precondition(!FileManager.default.fileExists(atPath:root.appendingPathComponent("child").path))}
    print("BROWSER_BOUNDARY_PASS"); exit(0)
}
let browser = NativeWorkbench(preferences:root, translate:{$0},openProjects:{fatalError("legacy projects unexpectedly started")})
precondition(browser.profilePersistent)
precondition(browser.web.configuration.userContentController.userScripts.isEmpty)
precondition(browser.web.customUserAgent == WKWebView().customUserAgent) // Match untouched platform default, which can be an empty string.
precondition(browser.web.url == nil) // No load, model call or service is required by initialization.
if mode == "srcdoc" {
    // Real WebKit engine, synthetic inline document; no remote site or model.
    browser.web.loadHTMLString("<iframe srcdoc=\"<p id='proof'>INLINE_CHILD_OK</p>\"></iframe>",baseURL:nil)
    func inspectChild() {
        browser.web.evaluateJavaScript("document.querySelector('iframe')?.contentDocument?.getElementById('proof')?.textContent") { value,_ in
            if value as? String == "INLINE_CHILD_OK" { print("INLINE_CHILD_WEBKIT_PASS");exit(0) }
            DispatchQueue.main.asyncAfter(deadline:.now()+0.1,execute:inspectChild)
        }
    }
    inspectChild();DispatchQueue.main.asyncAfter(deadline:.now()+12){fatalError("inline child blocked")};app.run();exit(0)
}
let store = browser.web.configuration.websiteDataStore.httpCookieStore
let cookie = HTTPCookie(properties:[.name:"TWOS_SYNTHETIC_BROWSER_TEST",.value:"not-an-auth-cookie",.domain:"twos-synthetic.invalid",.path:"/",.expires:Date(timeIntervalSinceNow:3600)])!
func finish(_ value:String) {
    print(value); fflush(stdout)
    DispatchQueue.main.asyncAfter(deadline:.now()+2) { app.terminate(nil) }
}
if mode == "write" {
    store.setCookie(cookie) { store.getAllCookies { values in
        precondition(values.contains(where:{$0.name == cookie.name && $0.value == cookie.value}))
        finish("BROWSER_PERSIST_WRITE_PASS")
    }}
} else if mode == "read" || mode == "isolated" {
    store.getAllCookies { values in
        precondition(values.contains(where:{$0.name == cookie.name && $0.value == cookie.value}) == (mode == "read"))
        finish(mode == "read" ? "BROWSER_RESTART_PASS" : "BROWSER_ISOLATION_PASS")
    }
} else { fatalError("unknown test mode") }
DispatchQueue.main.asyncAfter(deadline:.now()+20) { fatalError("WebKit callback timeout") }
app.run()
''')
    binary = root / 'browser-component'
    result = subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(root/'module-cache'),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120)
    assert result.returncode == 0, result.stderr
    return binary


def run(harness, mode, root):
    result = subprocess.run([str(harness),mode,str(root)],capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_official_location_restore_strips_tokens_rejects_external_and_symlink_storage(harness,tmp_path):
    assert 'BROWSER_BOUNDARY_PASS' in run(harness,'boundary',tmp_path/'preferences')


def test_actual_webkit_cookie_store_survives_process_restart_and_isolates_profiles(harness,tmp_path):
    one=tmp_path/'one';two=tmp_path/'two'
    assert 'BROWSER_PERSIST_WRITE_PASS' in run(harness,'write',one)
    before=json.loads((one/'official-browser-profile.json').read_text())
    assert 'BROWSER_RESTART_PASS' in run(harness,'read',one)
    assert json.loads((one/'official-browser-profile.json').read_text()) == before
    assert 'BROWSER_ISOLATION_PASS' in run(harness,'isolated',two)
    assert json.loads((two/'official-browser-profile.json').read_text()) != before


def test_inline_child_document_loads_with_production_navigation_policy(harness,tmp_path):
    assert 'INLINE_CHILD_WEBKIT_PASS' in run(harness,'srcdoc',tmp_path/'profile')


def test_native_browser_has_no_foreign_window_or_clipboard_controller():
    native=NATIVE.read_text(); browser=native.split('// Official pages own')[1].split('// The only child runtime')[0]
    assert 'window.getSelection()?.toString()' in browser
    assert 'placeDraft' in browser and 'handoffHandler' in browser
    assert 'NSPasteboard' not in browser and 'AXUIElement' not in browser and 'CGEvent' not in browser
    assert 'Process()' not in browser and 'codex://' not in browser
    assert 'didReceive challenge' not in browser and 'customUserAgent =' not in browser
    # Explicit instruction cards are isolated from the remote page's script world.
    assert 'in: Self.handoffWorld' in browser
    assert 'forMainFrameOnly: true' in browser
    assert 'contentWorld: Self.handoffWorld, name: "twosHandoff"' in browser
    assert 'name: "twosCodex"' not in browser
    assert '.prompt : .deny' in browser
    assert 'guard let safari = NSWorkspace.shared.urlForApplication' in browser
