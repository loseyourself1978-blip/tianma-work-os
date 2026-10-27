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
    code+='\n'+(ROOT/'packaging/macos/CodexAttachments.swift').read_text()+'\n'+(ROOT/'packaging/macos/CodexTelemetry.swift').read_text()+'\n'+(ROOT/'packaging/macos/NativeCodex.swift').read_text()+'\n'+(ROOT/'packaging/macos/IntegratedWorkbench.swift').read_text()
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
                precondition(client.handoffCandidate?.text == "One instruction" && client.handoffCandidate?.source == base && client.draftText.isEmpty,"selection must arrive in an exact handoff preview without altering a draft or prematurely executing")
                browser.placeDraft("Returned result",expectedSource:base) { ok in
                    precondition(ok)
                    browser.web.evaluateJavaScript("JSON.stringify({text:document.getElementById('draft').value,sends:window.sends})") { value, error in
                        precondition(error == nil)
                        let state = try! JSONSerialization.jsonObject(with:(value as! String).data(using:.utf8)!) as! [String:Any]
                        precondition(state["text"] as? String == "Existing draft\n\nReturned result" && state["sends"] as? Int == 0,"return must preserve the draft without submitting")
                        browser.placeDraft("Wrong discussion",expectedSource:base.appendingPathComponent("other")) { allowed in
                            precondition(!allowed)
                            verifyResultReturn()
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
func verifyResultReturn() {
    verifyHandoffEligibility {
    browser.web.evaluateJavaScript("document.getElementById('draft').value='';document.getElementById('draft').hidden=true;const writing=document.createElement('div');writing.setAttribute('data-markdown-text-style','assistant-message');writing.innerHTML='<div id=writing-editor contenteditable=true role=textbox>Original writing content</div>';document.body.prepend(writing);const editor=document.createElement('div');editor.id='composer-editor';editor.setAttribute('role','textbox');editor.contentEditable='true';editor.style.whiteSpace='pre-wrap';document.querySelector('form').prepend(editor)") { _, _ in
        browser.deliverResult("Verified synthetic result\n\n|item|status|\n|---|---|\n|one|ok|\n\nEnd.", id:"return-fixture", source:base) { state in
            guard state == "confirmed" else {
                browser.web.evaluateJavaScript("JSON.stringify({text:document.getElementById('composer-editor').innerText,html:document.getElementById('composer-editor').innerHTML})") { value, _ in
                    fatalError("real website send receipt: \(state); editor: \(String(describing:value))")
                }
                return
            }
            browser.deliverResult("Verified synthetic result", id:"return-fixture", source:base) { repeated in
                precondition(repeated == "confirmed")
                browser.web.evaluateJavaScript("document.getElementById('writing-editor').innerText === 'Original writing content' ? window.sends : -1") { value, _ in
                    precondition(value as? Int == 1,"result return is reconciled without a duplicate website send")
                    verifyDeferredReturn()
                }
            }
        }
    }
    }
}
func verifyDeferredReturn() {
    browser.web.evaluateJavaScript("const stop=document.createElement('button');stop.id='deferred-stop';stop.setAttribute('aria-label','停止');document.body.append(stop)") { _, _ in
        DispatchQueue.main.asyncAfter(deadline:.now()+0.5) {
            var item=CodexSubmission(id:"deferred-fixture",thread:"fixture-thread",directory:CodexDirectory(path:root.path,device:0,inode:0,isolated:true),text:"Fixture instruction",attachments:[],model:"fixture",effort:"low",mode:"send",createdAt:0,source:base.absoluteString,message:"",instructionHash:nil,state:"completed")
            item.result="Deferred verified result";client.ledger.submissions.append(item)
            workbench.returnDelivery(item.id,explicit:false)
            DispatchQueue.main.asyncAfter(deadline:.now()+0.4) {
                precondition(client.ledger.submissions.last?.returnState == "pending","a busy discussion defers the return without inserting a draft")
                browser.web.evaluateJavaScript("document.getElementById('deferred-stop').remove()") { _, _ in
                    var attempts=0
                    func verify() {
                        attempts += 1
                        if client.ledger.submissions.last?.returnState == "confirmed" {
                            browser.handoffReady?();browser.handoffReady?()
                            browser.web.evaluateJavaScript("window.sends") { value, _ in
                                precondition(value as? Int == 2,"idle transition automatically returns once; repeated ready events do not resend")
                                runRenderer()
                            }
                        } else if attempts < 60 { DispatchQueue.main.asyncAfter(deadline:.now()+0.1){verify()} }
                        else { fatalError("pending result was not automatically returned when the discussion became available") }
                    }
                    verify()
                }
            }
        }
    }
}
func verifyHandoffEligibility(_ completion: @escaping () -> Void) {
    browser.web.evaluateJavaScript(#"""
    const turn=document.createElement('article');turn.id='streaming-fixture';
    turn.innerHTML='<button id="fixture-stop" aria-label="停止">■</button><div id="summary-one" data-markdown-text-style="assistant-message">Public summary one</div><div id="summary-two" data-markdown-text-style="assistant-message">Public summary two</div><div id="final-fixture" data-markdown-text-style="assistant-message">Complete instruction including its final requirement<button style="color: red">Suggest another task</button><span role="button">Copy code</span></div>';
    document.body.append(turn);
    """#) { _, error in
        precondition(error == nil)
        DispatchQueue.main.asyncAfter(deadline:.now()+0.6) {
            browser.web.evaluateJavaScript("document.querySelectorAll('[data-twos-native-card]').length") { value, _ in
                precondition(value as? Int == 0,"the current Chinese Stop label prevents handoff of streamed summaries")
                browser.web.evaluateJavaScript("document.getElementById('fixture-stop').remove()") { _, _ in
                    DispatchQueue.main.asyncAfter(deadline:.now()+0.6) {
                        browser.web.evaluateJavaScript("document.getElementById('final-fixture').nextElementSibling?.hasAttribute('data-twos-native-card') && !document.getElementById('summary-one').nextElementSibling?.hasAttribute('data-twos-native-card') && !document.getElementById('summary-two').nextElementSibling?.hasAttribute('data-twos-native-card')") { value, _ in
                            precondition(value as? Bool == true,"only the final complete answer within a turn gets a handoff button")
                            verifyOutcomeCard {
                                browser.web.evaluateJavaScript("document.getElementById('streaming-fixture').remove()") { _, _ in completion() }
                            }
                        }
                    }
                }
            }
        }
    }
}
func verifyOutcomeCard(_ completion: @escaping () -> Void) {
    let instruction="Complete instruction including its final requirement"
    let old:[String:Any] = ["id":"old-blocked","source":base.absoluteString,"message":"","hash":NativeCodex.digest(Data(instruction.utf8)),"state":"completed","businessResult":"blocked","retryable":true,"createdAt":1,"cwd":root.path,"result":"RESULT: BLOCKED\nNo directory context was supplied."]
    browser.web.callAsyncJavaScript("await window.twosHandoffUpdate(record)", arguments:["record":old],in:nil,in:NativeWorkbench.handoffWorld) { _ in
        browser.web.evaluateJavaScript("(()=>{const c=document.getElementById('final-fixture').nextElementSibling;return !c.querySelector('button').disabled&&c.textContent.includes('Task BLOCKED')&&c.textContent.includes('Execution channel finished')&&c.querySelector('[data-twos-result]').open&&!c.querySelector('[data-twos-send-preview]').open&&c.querySelector('[data-twos-send-preview] summary').textContent==='View selected content'&&c.textContent.includes('No directory context')})()") { value,_ in
            precondition(value as? Bool == true,"clean body hash matches despite visible suggestion/copy controls; historical completed/BLOCKED remains actionable")
            var newer=old;newer["id"]="new-attempt";newer["createdAt"]=2;newer["state"]="running";newer["retryable"]=false;newer["businessResult"]="not_completed";newer["result"]=""
            browser.web.callAsyncJavaScript("await window.twosHandoffUpdate(newer);await window.twosHandoffUpdate(old)",arguments:["newer":newer,"old":old],in:nil,in:NativeWorkbench.handoffWorld) { _ in
                browser.web.evaluateJavaScript("(()=>{const c=document.getElementById('final-fixture').nextElementSibling;return c.querySelector('button').disabled&&c.textContent.includes('Running')&&!c.textContent.includes('Task BLOCKED')})()") { value,_ in
                    precondition(value as? Bool == true,"older receipt must not overwrite a newer attempt after reload")
                    browser.web.callAsyncJavaScript("const reply=document.getElementById('final-fixture');const legacy={...record,id:'legacy-receipt',createdAt:3,result:'Legacy receipt preserved'};legacy.hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(reply.innerText)))].map(x=>x.toString(16).padStart(2,'0')).join('');await window.twosHandoffUpdate(legacy);return JSON.stringify({receipt:reply.nextElementSibling.textContent,style:reply.querySelector('button').getAttribute('style'),roleStyle:reply.querySelector('[role=button]').getAttribute('style')});",arguments:["record":old],in:nil,in:NativeWorkbench.handoffWorld) { outcome in
                        guard case .success(let value)=outcome else { fatalError("legacy receipt verification failed") }
                        let observed=try! JSONSerialization.jsonObject(with:(value as! String).data(using:.utf8)!) as! [String:Any]
                        precondition((observed["receipt"] as? String)?.contains("Legacy receipt preserved") == true && observed["style"] as? String == "color: red" && observed["roleStyle"] is NSNull,"legacy hashes and styles: \(value)")
                        completion()
                    }
                }
            }
        }
    }
}
func runRenderer() {
    let script = #"""
    (()=>{
      const $=id=>document.getElementById(id),r=(kind,payload)=>window.twosReceive({kind,payload});
      const checks=[];const assert=(value,label)=>{if(!value)throw Error(label);checks.push(label)};
      r('locale',{zh:true});r('models',{items:[{model:'model-a',displayName:'Model A'},{model:'model-b',displayName:'Model B',supportedReasoningEfforts:[{reasoningEffort:'low'},{reasoningEffort:'high'}],defaultReasoningEffort:'low'}]});
      r('threads',{items:[{id:'fixture-thread',name:'Travel task',cwd:'/synthetic/workspace'}]});
      r('thread',{thread:{id:'fixture-thread',cwd:'/synthetic/workspace'}});
      assert($('threads').selectedOptions[0].textContent==='Travel task','thread/read without a name keeps the list name and real ID');
      r('threads',{items:[{id:'other-thread',cwd:'/synthetic/other-folder',preview:'TWOS controller-verified execution context / internal scope'}]});
      assert($('threads').value==='fixture-thread'&&$('threads').selectedOptions[0].textContent==='Travel task','refresh with the selected conversation outside the page retains its label');
      assert(Array.from($('threads').options).find(x=>x.value==='other-thread').textContent==='other-folder','unnamed conversation uses its actual folder instead of internal context');
      r('thread',{thread:{id:'fixture-thread',name:'Renamed travel task',cwd:'/synthetic/workspace'}});
      assert($('threads').selectedOptions[0].textContent==='Renamed travel task','a real updated name replaces the selected option label');
      r('control',{connected:true,busy:true,controllable:true,desktopRunning:false,historyReady:true,threadId:'fixture-thread'});
      $('draft').value='Continue';$('draft').dispatchEvent(new Event('input'));
      assert(!$('draft').disabled&&!$('model').disabled&&!$('send').disabled&&!$('next-turn').hidden,'running composer supports Steer and next-turn model choice');
      assert($('mode').tagName==='SELECT'&&$('mode').value==='steer'&&$('new-task'),'visible task and Steer/Queue entrypoints');
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
      r('control',{connected:true,busy:false,controllable:true,historyReady:true,threadId:'fixture-thread'});
      r('result',{available:true,businessResult:'blocked',transport:'completed'});r('turnCompleted',{status:'completed'});
      $('draft').value='Next';$('draft').dispatchEvent(new Event('input'));
      assert($('status').textContent.includes('BLOCKED'),'business BLOCKED survives completed event and composer updates');
      r('sent',{text:'late acknowledgement'});assert($('status').textContent.includes('BLOCKED'),'late sending receipt cannot erase a terminal business failure');
      r('result',{available:true,businessResult:'reported_pass',transport:'completed'});
      assert($('status').textContent.includes('尚待验收'),'executor PASS is not independent artifact acceptance');
      r('result',{available:true,source:'https://example.invalid/c/source'});
      assert(!$('return').hidden,'verified completed result has return action');
      r('control',{connected:true,busy:false,uncertain:true,historyReady:true,threadId:'fixture-thread'});
      $('draft').value='Do not repeat';$('draft').dispatchEvent(new Event('input'));
      assert($('send').disabled&&!$('reconnect').hidden,'unknown execution blocks resubmit and has recovery action');
      assert($('model').tagName==='SELECT'&&$('model').options.length===2,'models use native selectable dropdown');
      r('control',{connected:true,busy:false,historyReady:true,controllable:true,threadId:'fixture-thread',nextModel:'unavailable-model'});
      assert($('model').value==='unavailable-model'&&$('send').disabled,'missing saved model is visible and cannot silently fall back');
      r('control',{connected:true,busy:false,historyReady:true,controllable:true,threadId:'fixture-thread',nextModel:'model-b',nextEffort:'high'});
      assert($('model').value==='model-b'&&$('effort').value==='high'&&!$('send').disabled,'native next-turn settings restore the actual selected model and effort');

      r('control',{connected:true,busy:true,controllable:true,historyReady:true,threadId:'fixture-thread',turnId:'same-turn',cwd:'/synthetic/workspace',actualModel:'model-b',stopRequested:true,waitingRequests:0});
      assert($('stop').disabled&&$('status').textContent.includes('等待当前轮实际结束'),'requesting stop is not stopped');
      assert($('session-identity').textContent.includes('same-turn')&&!$('session-details').hidden,'technical thread and turn details available');
      assert($('session-facts').textContent.includes('/synthetic/workspace')&&!$('session-facts').textContent.includes('same-turn'),'session information is readable without raw transport identifiers');
      assert(!$('session-technical').open,'raw technical identity is behind a separate disclosure');
      r('event',{method:'turn/plan/updated',params:{turnId:'same-turn',plan:[{step:'Check actual output',status:'in_progress'},{step:'Verify',status:'pending'}]}});
      assert($('item-plan-same-turn').textContent.includes('进行中')&&$('item-plan-same-turn').textContent.includes('等待中'),'actual plan state visible');
      r('event',{method:'item/started',params:{item:{id:'cwd-command',type:'commandExecution',command:'pwd',cwd:'/synthetic/workspace',status:'inProgress'}}});
      r('event',{method:'item/commandExecution/outputDelta',params:{itemId:'cwd-command',delta:'check output'}});
      assert($('item-cwd-command').textContent.includes('/synthetic/workspace')&&$('item-cwd-command').textContent.includes('check output'),'command cwd and live output visible');
      r('event',{method:'item/completed',params:{item:{id:'file-diff',type:'fileChange',status:'completed',changes:[{path:'index.html',diff:'+actual change'}]}}});
      assert($('item-file-diff').querySelector('[data-operation=browser]')&&$('item-file-diff').textContent.includes('+actual change'),'real diff and artifact actions coexist');
      r('event',{method:'item/started',params:{item:{id:'tool-activity',type:'mcpToolCall',server:'fixture',tool:'check',status:'inProgress',arguments:{test:true}}}});
      assert($('item-tool-activity').textContent.includes('fixture')&&$('item-tool-activity').textContent.includes('进行中'),'public tool activity visible');
      r('event',{method:'item/completed',params:{item:{id:'context-input',type:'userMessage',content:[{type:'text',text:'TWOS controller-verified execution context / path context'},{type:'text',text:'Visible business instruction'}]}}});
      assert($('item-context-input').querySelector('details')&&!$('item-context-input').querySelector('details').open&&$('item-context-input').textContent.includes('Visible business instruction'),'technical context is collapsed while full business message stays visible');
      r('approval',{key:'request-one',method:'item/tool/requestUserInput',params:{threadId:'fixture-thread',turnId:'same-turn',itemId:'question',questions:[{id:'choice',question:'Choose test scope',options:[{label:'Local',description:'Existing scope'}]}]}});
      assert($('approvals').querySelector('input[type=radio]')&&$('approvals').textContent.includes('same-turn'),'real input options and request scope shown');
      r('approvalPending',{key:'request-one'});
      assert($('approvals').querySelector('button').disabled&&!$('approvals').querySelector('.approval-wait').hidden,'answered approval waits for service resolution');
      r('answered',{key:'request-one'});assert(!$('approvals').children.length,'resolved approval removed');
      r('artifacts',{threadId:'fixture-thread',cwd:'/synthetic/workspace',items:[{path:'index.html',bytes:42,html:true}]});
      assert(!$('artifact-panel').hidden&&$('artifact-items').querySelector('[data-operation=browser]'),'file entry opens via product action');
      assert($('artifact-items').querySelector('[data-operation=save]').textContent==='另存为…','artifact list exposes the native save action');
      r('artifactContent',{threadId:'fixture-thread',path:'/synthetic/workspace/index.html',text:'<script>window.unsafePreview=true</script>'});
      assert($('artifact-view').open&&$('artifact-text').textContent.includes('<script>')&&!window.unsafePreview,'HTML preview is inert text without native bridge execution');
      $('artifact-view').close();
      r('displaySnapshot',{items:[{id:'restored-command',type:'commandExecution',command:'check',aggregatedOutput:'preserved output',cwd:'/synthetic/workspace'}]});
      assert($('item-restored-command').textContent.includes('preserved output'),'live display snapshot restores streamed items');
      r('artifactOpened',{opened:true,path:'/synthetic/workspace/index.html'});
      assert($('notice-text').textContent.includes('仍需实际检查'),'opening is not falsely reported as browser acceptance');

      const inlineAttachment='Local parsing coverage: docx_body_tables_text. No images.\nText attachment supplied inline: 中文.docx\n--- BEGIN ATTACHMENT CONTENT ---\n<script>not executable</script> actual body';
      r('event',{method:'item/completed',params:{item:{id:'attachment-readable',type:'userMessage',content:[{type:'text',text:inlineAttachment}]}}});
      const attachmentCard=$('item-attachment-readable');
      assert(!attachmentCard.querySelector('details').open&&attachmentCard.querySelector('summary').textContent.includes('中文.docx')&&attachmentCard.querySelector('pre').textContent===inlineAttachment&&!attachmentCard.querySelector('script'),'attachment transport details are collapsed with exact safe content preserved');
      r('event',{method:'error',params:{willRetry:true,message:'Reconnecting...'}});
      assert(!$('notice').hidden,'real service reconnect is visible');
      r('event',{method:'item/agentMessage/delta',params:{itemId:'recovered-response',delta:'resumed'}});
      assert($('notice').hidden,'new real activity clears only the stale reconnect notice');

      const receipt='RESULT: PARTIAL\nREPORTED_FILE: /synthetic/workspace/index.html\nKNOWN_LIMITATIONS: Browser check NOT_RUN\nONLINE_RESOURCES_USED: None\nEXACT_LOCAL_OPEN_METHOD: <script>unsafe()</script>';
      r('event',{method:'item/completed',params:{item:{id:'readable-receipt',type:'agentMessage',text:receipt}}});
      const card=$('item-readable-receipt');
      assert(card.querySelector('dl').textContent.includes('PARTIAL')&&card.querySelector('dl').textContent.includes('Browser check NOT_RUN')&&card.querySelector('pre').textContent===receipt&&!card.querySelector('details').open&&!card.querySelector('script'),'readable receipt preserves exact original and all known limitations without a false PASS');
      assert(card.querySelector('.message-actions button').textContent==='复制'&&$('send').getAttribute('aria-label')==='发送','compact controls retain explicit accessible actions');
      r('artifacts',{threadId:'fixture-thread',automatic:true,items:[{path:'index.html',bytes:42,html:true}]});
      assert(!$('result-files').hidden&&$('result-files').textContent.includes('工作目录文件')&&$('result-files').querySelector('[data-operation=browser]'),'verified workspace files surface beside result without claiming they were all generated this turn');
      const saveFile=$('result-files').querySelector('[data-operation=save]');
      assert(saveFile&&saveFile.getBoundingClientRect().height>0&&!saveFile.closest('details:not([open])'),'save as is visible beside the result');
      r('artifactSaved',{threadId:'fixture-thread',destination:'/synthetic/exports/report.md'});
      assert($('notice-text').textContent.includes('副本已保存')&&$('notice-text').textContent.includes('/synthetic/exports/report.md'),'only the native save completion reports success and the chosen location');
      r('artifactSaved',{threadId:'other-thread',destination:'/synthetic/exports/wrong.md'});
      assert(!$('notice-text').textContent.includes('wrong.md'),'late save receipt cannot cross conversations');
      const openFile=$('result-files').querySelector('[data-operation=browser]');
      assert(openFile.getBoundingClientRect().height>0&&!openFile.closest('details:not([open])'),'open webpage is visible without expanding a file disclosure');
      r('artifacts',{threadId:'other-thread',automatic:true,items:[{path:'wrong.html',bytes:12,html:true}]});
      assert(!$('result-files').textContent.includes('wrong.html'),'late artifact response cannot cross conversations');
      const longReply='A visible line\n\n'.repeat(150);
      r('event',{method:'item/completed',params:{item:{id:'long-reply',type:'agentMessage',text:longReply}}});
      $('timeline').scrollTop=0;
      r('event',{method:'item/agentMessage/delta',params:{itemId:'long-reply',delta:'Final line'}});
      assert($('timeline').scrollTop===0&&!$('latest').hidden,'streaming preserves reading position and offers jump to latest');
      $('latest').click();assert($('latest').hidden&&$('timeline').scrollTop>0,'jump to latest actually reaches the newest output');
      let sends=0;const intercept=e=>{e.preventDefault();e.stopImmediatePropagation();sends++};
      $('composer').addEventListener('submit',intercept,true);
      $('draft').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
      assert(sends===1,'Enter submits a ready composer');
      $('draft').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',shiftKey:true,bubbles:true,cancelable:true}));
      $('draft').dispatchEvent(new CompositionEvent('compositionstart'));
      $('draft').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
      $('draft').dispatchEvent(new CompositionEvent('compositionend'));
      $('draft').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true,cancelable:true}));
      assert(sends===1,'Shift+Enter and Safari composition-end Enter do not send a message');
      $('composer').removeEventListener('submit',intercept,true);
      r('queue',{paused:true,items:[]});assert($('queue-panel').hidden,'an empty paused queue never offers a meaningless continue action');

      // R2: real WebKit rendering with explicitly synthetic service metadata.
      r('locale',{zh:false});assert($('language').value==='en-US'&&$('directory-mode').options[1].textContent.includes('Existing project'),'language entry and directory modes visible');
      $('draft').value='用户正文 untouched';r('locale',{zh:true});assert($('draft').value==='用户正文 untouched','language never translates or clears the draft');
      r('telemetry',{connected:true,accountVerified:true,now:1000,authentication:'chatgpt',plan:'pro',limitsUpdated:990,usageUpdated:990,errors:{},observedTurns:2,observedTools:3,limits:{rateLimits:{primary:{usedPercent:80}},rateLimitsByLimitId:{codex:{primary:{usedPercent:12,windowDurationMins:10080,resetsAt:2000},secondary:null,credits:{balance:'0',hasCredits:false,unlimited:false}},other:{primary:{usedPercent:30,windowDurationMins:300,resetsAt:2000}}}},usage:{summary:{lifetimeTokens:100},dailyUsageBuckets:[]}});
      assert($('usage-windows').children.length===2&&!$('usage-windows').textContent.includes('80%'),'quota buckets do not double-count legacy mirror');
      assert($('usage-windows').textContent.replace(/,/g,'').includes('10080')&&$('usage-windows').textContent.includes('300'),'window lengths come from service');
      assert($('usage-tokens').textContent.includes('未知')&&!$('usage-tokens').textContent.includes('0 / 0'),'missing token counters are unknown, not zero');
      r('telemetry',{connected:false,accountVerified:false,now:1000,authentication:'unknown',plan:'unknown',errors:{limits:'capacity'},limits:{rateLimits:{primary:{usedPercent:99}}}});
      assert(!$('usage-windows').textContent.includes('99')&&$('usage-error').textContent.includes('容量'),'account verification hides old data and capacity is distinct from quota');
      r('telemetry',{connected:true,accountVerified:true,now:1000,authentication:'chatgpt',plan:'pro',errors:{},run:{state:'waiting_input',started:900,elapsed:100,observedActive:60,observedWait:40,lastActivity:999,planDone:1,planTotal:3,planRevisions:1,requestedModel:'model-a',returnedModel:'unknown',returnState:'not_recorded',businessResult:'unverified',eta:{available:false,reason:'waiting_user'}}});
      assert($('run-compact').textContent.includes('等待你的输入')&&$('run-eta').textContent.includes('暂停'),'user wait pauses ETA');
      r('telemetry',{connected:true,accountVerified:true,now:1000,authentication:'chatgpt',plan:'pro',errors:{},run:{state:'running',started:900,elapsed:100,observedActive:100,observedWait:0,lastActivity:999,planDone:2,planTotal:4,planRevisions:2,requestedModel:'model-a',returnedModel:'unknown',returnState:'not_recorded',businessResult:'unverified',eta:{available:true,low:20,high:80,samples:3,confidence:'low',updated:999,reassessed:true}}});
      assert($('run-eta').textContent.includes('TWOS 本地估计')&&$('run-detail').textContent.includes('超时后已重新评估'),'ETA source and reassessment are explicit');
      assert(!$('run-detail').textContent.includes('not_recorded')&&!$('run-detail').textContent.includes('unverified'),'run result states use the selected language');

      // U01/U02 TEST/FIXTURE values, never presented as live account data.
      const sample={connected:true,accountVerified:true,now:1000,limitsUpdated:999,authentication:'fixture',plan:'TEST',errors:{}};
      for(const remaining of [100,76,50,1,0,76.25]){
       r('telemetry',{...sample,limits:{rateLimits:{limitId:'TEST',primary:{usedPercent:100-remaining,windowDurationMins:73}}}});
       const arc=$('usage-compact').querySelector('.ring-value'),svg=$('usage-compact').querySelector('svg');
       assert(svg.textContent===remaining+'%'&&(remaining===0?!arc:remaining===100?!arc.hasAttribute('stroke-dasharray'):arc.getAttribute('stroke-dasharray')===remaining+' '+(100-remaining)),'remaining ring geometry '+remaining);
      }
      for(const bad of [-1,101,null,'24',true]){
       r('telemetry',{...sample,limits:{rateLimits:{primary:{usedPercent:bad}}}});
       assert($('usage-compact').querySelector('svg').textContent==='—'&&!$('usage-compact').querySelector('.ring-value'),'invalid percentage remains unknown '+bad);
      }
      r('telemetry',{...sample,limits:{rateLimits:{primary:{remainingPercent:76,windowDurationMins:73}}}});
      assert($('usage-compact').querySelector('svg').textContent==='76%','remaining service field is not inverted');
      r('telemetry',{...sample,connected:false,limits:{rateLimits:{primary:{usedPercent:24},secondary:{usedPercent:50}}}});
      assert($('usage-compact').querySelectorAll('svg').length===2&&$('usage-reading').textContent.includes('上次')&&$('usage-compact').querySelector('svg').getAttribute('aria-label').includes('上次'),'distinct windows and stale accessible state');
      r('telemetry',{...sample,accountVerified:false,limits:{rateLimits:{primary:{usedPercent:24}}}});
      assert(!$('usage-compact').textContent.includes('76%'),'unverified account never displays previous ring');
      r('telemetry',{...sample,run:{state:'running',elapsed:260,lastActivity:999,eta:{available:true,low:120,high:300,samples:3,confidence:'low',updated:999},workload:{available:true,remainingPercent:40,basis:'equal_plan_items',planVersion:2,updated:999}}});
      assert($('run-eta-value').textContent.includes('2分')&&$('run-work').textContent==='40%（估算）'&&$('run-metrics').children.length===3,'ETA elapsed workload are primary parallel fields');
      assert($('run-detail').textContent.includes('等权')&&$('run-scope').textContent.includes('仅当前执行'),'work scope and non-time basis are visible');
      $('pet-control').click();assert(!$('pet-info').hidden&&$('pet-control').getAttribute('aria-expanded')==='true'&&$('pet-reason').textContent.includes('暂不可用'),'unbundled Nyra explains unavailable without a fake toggle');
      r('locale',{zh:false});assert($('pet-control').textContent.includes('view status')&&$('elapsed-label').textContent==='Elapsed'&&$('work-label').textContent==='Work remaining','new controls support English');
      $('pet-control').click();r('locale',{zh:true});assert($('pet-info').hidden,'pet disclosure closes without controlling model or floating state');
      r('nyra',{available:true,visible:false,observed:true});assert($('pet-control').textContent.includes('显示夜璃'),'actual helper state shows show action');
      r('nyra',{available:true,visible:true,observed:true});assert($('pet-control').textContent.includes('隐藏夜璃')&&$('pet-binding').textContent.includes('尚未关联'),'actual visibility does not imply run binding');
      r('nyra',{available:true,visible:true,observed:true,binding:'CONNECTED_READONLY'});assert($('pet-binding').textContent.includes('只读任务状态')&&$('pet-binding').textContent.includes('不代表执行或验收'),'observed same-instance readonly connection never claims acceptance');
      r('nyra',{available:true,visible:true,observed:true,binding:'NOT_CONNECTED'});assert($('pet-binding').textContent.includes('尚未关联'),'disconnect removes stale connected label');
      r('nyra',{available:true,visible:true,pending:true});assert($('pet-control').disabled,'pending control cannot double-toggle');
      r('nyra',{available:false,reason:'NYRA_HELPER_NOT_BUNDLED'});
      r('event',{method:'item/completed',params:{item:{id:'image-name',type:'userMessage',content:[{type:'text',text:'Image attachment supplied next: 图A.png\nSource SHA256: abc'}]}}});assert($('item-image-name').querySelector('summary').textContent==='图片 · 图A.png'&&!$('item-image-name').querySelector('details').open,'image transport label is localized and collapsed');
      window.twosTelemetry.selectThread('new-empty');assert($('run-compact').textContent.includes('暂无已观测运行')&&!$('run-detail').textContent.includes('model-a'),'switching clears the previous thread observation immediately');
      $('folder-path').textContent='/old-folder';r('newTask',{});assert($('folder-path').textContent===''&&$('confirm-folder').disabled,'new task never keeps the previous directory preview');
      r('attachments',{items:[{id:'parsed-doc',name:'样本.docx',bytes:240,coverage:'docx_body_tables_text'}]});assert($('attachments').textContent.includes('不含图片')&&$('attachments').textContent.includes('尚未发送'),'parsed attachment coverage is not model receipt');
      r('queue',{paused:true,items:[{id:'language-edit',text:'Original',state:'queued',editable:true,model:'model-a'}]});$('queue-items').querySelector('button').click();const editing=$('queue-items').querySelector('textarea');editing.value='保留编辑草稿';editing.dispatchEvent(new Event('input'));r('locale',{zh:false});r('queue',{paused:true,items:[{id:'language-edit',text:'Original',state:'queued',editable:true,model:'model-a'}]});assert($('queue-items').querySelector('textarea').value==='保留编辑草稿','queue draft survives locale and queue refresh');
      r('locale',{zh:true});r('attachments',{items:[]});r('queue',{paused:true,items:[]});
      assert($('usage-title').textContent==='额度与用量'&&$('run-title').textContent==='运行活动','observability labels switch with TWOS locale');
      $('usage-panel').open=true;$('run-panel').open=true;
      assert($('telemetry').scrollHeight>0&&$('telemetry').clientHeight<=innerHeight*.35,'expanded telemetry has bounded scroll area');
      $('usage-panel').open=false;$('run-panel').open=false;
      // Real WebKit layout: simultaneous expandable panels must never move
      // the permanent composer below the viewport, even with long scope data.
      r('approval',{key:'geometry-request',method:'item/commandExecution/requestApproval',decisions:['decline'],params:{threadId:'fixture-thread',turnId:'same-turn',itemId:'geometry',command:'python3 -c '+ 'x'.repeat(180),cwd:'/synthetic/workspace',reason:'Review this command'}});
      $('approvals').querySelector('details').open=true;
      $('queue-panel').hidden=false;$('queue-items').textContent='Queued requirement '.repeat(150);
      $('session-details').open=true;$('session-technical').open=true;
      $('artifact-items').append(document.createTextNode('Existing file '.repeat(100)));
      const composer=$('composer').getBoundingClientRect(),send=$('send').getBoundingClientRect();
      assert(composer.top>=0&&composer.bottom<=innerHeight+1&&send.bottom<=innerHeight+1,'composer and send remain in viewport with files approval and queue expanded');
      assert($('approvals').clientHeight>0&&$('artifact-panel').clientHeight>0&&$('queue-panel').clientHeight>0,'expanded panels remain accessible in their own scroll areas');
      r('control',{connected:true,busy:true,awaitingTurn:true,controllable:true,historyReady:true,threadId:'fixture-thread',mode:'steer'});
      assert($('send').disabled&&$('stop').hidden&&$('status').textContent.includes('等待实际轮次开始'),'accepted queue without a real turn is not shown as working or steerable');
      r('control',{connected:true,busy:false,uncertain:true,controllable:true,historyReady:true,threadId:'fixture-thread'});
      r('queue',{paused:true,items:[{id:'saved-queue',text:'Exact saved input',state:'unknown',recoverable:true}]});
      assert($('queue-items').textContent.includes('核验并启动已保存输入'),'unknown saved queue has explicit identity-checked recovery');

      assert(document.documentElement.scrollWidth<=innerWidth+2,'no horizontal viewport overflow');
      return checks;
    })()
    """#
    client.web.evaluateJavaScript(script) { value, error in
        precondition(error == nil,"renderer: \(String(describing:error))")
        precondition((value as? [String])?.count == 99, "all prior checks plus Nyra visibility and readonly connection checks must run")
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
            body=b'<!doctype html><meta charset="utf-8"><div data-message-author-role="assistant">Earlier official answer</div><div data-markdown-text-style="reasoning-summary">Public summary</div><div data-markdown-text-style="assistant-message">Latest official answer<button>Suggested next instruction</button></div><div data-markdown-text-style="assistant-message" style="display:none">Hidden variant</div><p id="answer">Fixture instruction</p><form onsubmit="window.sends++;const m=document.createElement(\'div\');const heading=document.createElement(\'h4\');heading.textContent=\'You said:\';const text=document.createElement(\'p\');m.append(heading,text);const editor=document.getElementById(\'composer-editor\');text.textContent=editor?editor.innerText:document.getElementById(\'draft\').value;const shared=document.createElement(\'section\');const wrap=document.createElement(\'div\');wrap.append(heading);m.prepend(wrap);shared.append(m);const assistant=document.createElement(\'h4\');assistant.textContent=\'ChatGPT said:\';const reply=document.createElement(\'div\');reply.setAttribute(\'data-markdown-text-style\',\'assistant-message\');reply.textContent=\'Receipt response\';shared.append(assistant,reply);document.body.append(shared);if(editor)editor.textContent=\'\';document.getElementById(\'draft\').value=\'\';return false"><textarea id="draft"></textarea><button data-testid="send-button">Send</button></form><script>window.sends=0</script>'
            self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        result=subprocess.run([str(integrated_harness),str(tmp_path/'prefs'),f'http://127.0.0.1:{server.server_port}/',str(ROOT/'static_cockpit')],capture_output=True,text=True,timeout=40)
        assert result.returncode==0,result.stderr
        assert 'ONE_WINDOW_HANDOFF_RETURN_UI_PASS' in result.stdout
    finally:server.shutdown();server.server_close();thread.join()
