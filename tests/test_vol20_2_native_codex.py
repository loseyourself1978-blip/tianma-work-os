"""Production native protocol state machine. Synthetic thread IDs only, no provider calls."""
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='Native macOS client')

@pytest.fixture(scope='module')
def native_client(tmp_path_factory):
    root = tmp_path_factory.mktemp('native-codex-state')
    production = (ROOT/'packaging/macos/TianmaLauncher.swift').read_text().split('// The only child runtime',1)[0]
    production += (ROOT/'packaging/macos/NativeCodex.swift').read_text()
    harness = r'''
let app = NSApplication.shared
let root = URL(fileURLWithPath: CommandLine.arguments[1])
let resources = URL(fileURLWithPath: CommandLine.arguments[2])
try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
let id = UUID().uuidString, other = UUID().uuidString
let client = NativeCodex(resources: resources, preferences: root.appendingPathComponent("prefs"), translate: {$0})
client.connected = true; client.ownerDesktopRunning = {false}; client.modelIDs = ["synthetic-model"]
func result(_ result: [String: Any], id: Int? = nil) {
    let value: [String: Any] = ["id": id ?? client.requestID, "result": result]
    client.receive(try! JSONSerialization.data(withJSONObject: value) + Data([10]))
}
func event(_ method: String, _ params: [String: Any]) {
    client.receive(try! JSONSerialization.data(withJSONObject: ["method": method, "params": params]) + Data([10]))
}
func select(_ tid: String) {
    client.selectThread(tid)
    result(["thread": ["id": tid, "cwd": root.path, "status": ["type":"notLoaded"]]])
    result(["data": [["id":"old-turn", "status":"completed", "items":[]]]])
}
select(id)
precondition(client.threadID == id && client.historyReady && !client.isBusy)
precondition(client.requestID == 2, "select must only read metadata/history")
client.stage("Hand off one", source: URL(string:"https://chatgpt.com/c/synthetic-source")!)
client.saveDraft("Owner draft")
select(other); precondition(client.draftText.isEmpty)
client.saveDraft("Other draft")
select(id); precondition(client.draftText == "Owner draft")
client.stage("And add this", source: URL(string:"https://chatgpt.com/c/synthetic-source")!)
precondition(client.draftText == "Owner draft\n\nAnd add this")
let before = client.requestID
client.ownerDesktopRunning = {true}
client.sendTurn(client.draftText, model:"synthetic-model")
precondition(client.requestID == before && !client.isBusy, "active desktop cannot receive a duplicate execution")
client.ownerDesktopRunning = {false}
client.sendTurn(client.draftText, model:"synthetic-model")
precondition(client.isBusy && client.requestID == before+1 && client.lockFD >= 0, "send state: busy=\(client.isBusy) req=\(client.requestID-before) lock=\(client.lockFD) ready=\(client.historyReady) uncertain=\(client.uncertain) notices=\(client.pendingUI.filter { $0["kind"] as? String == "notice" })")
client.sendTurn("double click", model:"synthetic-model")
precondition(client.requestID == before+1, "double submit must not create another request")
let competitor = NativeCodex(resources: resources, preferences:root.appendingPathComponent("another-profile"), translate:{$0})
precondition(!competitor.acquireLock(id), "separate TWOS profiles cannot write one thread")
result(["thread":["id":id,"cwd":root.path,"status":["type":"idle"]],"cwd":root.path])
let startRequest = client.requestID
precondition(startRequest == before+2)
event("turn/started",["threadId":id,"turn":["id":"new-turn"]])
event("item/completed",["threadId":id,"turnId":"new-turn","item":["id":"answer","type":"agentMessage","phase":"final_answer","text":"Actual fixture answer"]])
event("turn/completed",["threadId":id,"turn":["id":"new-turn","status":"completed"]])
precondition(!client.isBusy && client.lockFD == -1 && client.lastResult == "Actual fixture answer")
result(["turn":["id":"new-turn"]], id:startRequest)
precondition(!client.isBusy && client.readMap("codex-pending.json")[id] == nil,"late start acknowledgement must not resurrect finished work")
precondition(client.resultSource!.absoluteString == "https://chatgpt.com/c/synthetic-source")
precondition(client.draftText.isEmpty)
precondition(competitor.acquireLock(id)); competitor.releaseLock()
// Reconstruct the production client from persisted preferences and provider history.
let restarted = NativeCodex(resources: resources, preferences:root.appendingPathComponent("prefs"),translate:{$0})
restarted.restoreDraft(); restarted.connected = true; restarted.ownerDesktopRunning = {false}
precondition(restarted.restoringThread == id)
restarted.selectThread(id)
restarted.callbacks.removeValue(forKey: restarted.requestID)!(["thread":["id":id,"cwd":root.path]])
restarted.callbacks.removeValue(forKey: restarted.requestID)!(["data":[["id":"new-turn","status":"completed","items":[["id":"answer","type":"agentMessage","text":"Actual fixture answer"]]]]])
precondition(restarted.lastResult == "Actual fixture answer" && restarted.resultSource == client.resultSource,"restart must recover the result and original discussion")
// Raw reasoning is not passed into the UI, only published summaries.
event("item/completed",["threadId":id,"item":["id":"reason","type":"reasoning","summary":["Published summary"],"content":["RAW_NOT_FOR_DISPLAY"]]])
let visible = String(data:try JSONSerialization.data(withJSONObject:client.pendingUI),encoding:.utf8)!
precondition(visible.contains("Published summary") && !visible.contains("RAW_NOT_FOR_DISPLAY"))
// Stale thread/read responses cannot switch back after a later selection.
client.selectThread(id); let stale = client.requestID
client.selectThread(other); let fresh = client.requestID
result(["thread":["id":other,"cwd":root.path]],id:fresh)
result(["data":[]])
result(["thread":["id":id,"cwd":root.path]],id:stale)
precondition(client.threadID == other)
// Only the current result is returned, never the most recent draft's origin.
precondition(client.lastResult.isEmpty && client.resultSource == nil)
// An unconfirmed request is not cleared by older unrelated terminal turns.
client.saveMap([other:"unconfirmed:old-turn"],"codex-pending.json")
client.loadHistory(older:false)
result(["data":[["id":"old-turn","status":"completed","items":[]],["id":"older-turn","status":"completed","items":[]]]])
precondition(client.readMap("codex-pending.json")[other] != nil)
print("NATIVE_CONTEXT_STATE_PASS")
exit(0)
'''
    source = root/'main.swift'; source.write_text(production+harness)
    binary=root/'native-client'
    compiled=subprocess.run(['xcrun','swiftc','-swift-version','5','-module-cache-path',str(root/'cache'),str(source),'-o',str(binary)],capture_output=True,text=True,timeout=120)
    assert compiled.returncode==0,compiled.stderr
    return binary


def test_native_context_identity_restart_duplicate_and_origin_boundaries(native_client,tmp_path):
    ran=subprocess.run([str(native_client),str(tmp_path/'case'),str(ROOT/'static_cockpit')],capture_output=True,text=True,timeout=45)
    assert ran.returncode==0,ran.stderr
    assert 'NATIVE_CONTEXT_STATE_PASS' in ran.stdout
