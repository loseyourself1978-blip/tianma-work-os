// TEST/FIXTURE ONLY. No external connection, credentials or model request.
const assert=(x,m)=>{if(!x)throw Error(m)},wait=()=>new Promise(r=>setTimeout(r,500));
const api=()=>window.twosProviderDOM,card=()=>document.getElementById('answer').nextElementSibling;
await wait();
// Current providers reset native form appearance. Our one scoped checkbox must
// remain visibly operable without applying a global override to their controls.
const reset=document.createElement('style');reset.textContent='input[type=checkbox]{appearance:none;width:0;height:0;padding:0;border:0;}';document.head.append(reset);
const checkbox=document.querySelector('[data-twos-automatic]');
assert(checkbox.getBoundingClientRect().width>=16&&checkbox.getBoundingClientRect().height>=16&&getComputedStyle(checkbox).webkitAppearance==='checkbox','R4 checkbox survives provider form CSS reset');reset.remove();
assert(api().observe().state==='idle','ordinary reply is observable');
assert(card()?.matches('[data-twos-native-card]')&&!card().querySelector('button').disabled,'ordinary non-code reply has a usable card');
assert(api().latest().message==='conversation-turn-1','canonical source identity');
const original=api().latest().text;assert(original.includes('Shapes')&&original.includes('shape')&&original.includes('square'),'complete prose/list/table/code content');
// Hidden compatibility fields, sidebar search and writing editors are not composers.
const noise=document.createElement('div');noise.innerHTML='<div aria-hidden=true><textarea>hidden</textarea></div><aside><textarea>search</textarea></aside><div data-message-author-role=assistant hidden><div contenteditable=true role=textbox>writing</div></div>';
document.body.append(noise);await wait();assert(api().observe().state==='idle','hidden and sidebar inputs excluded');
const draft=document.getElementById('draft');draft.hidden=true;
const outer=document.createElement('div');outer.contentEditable=true;outer.setAttribute('role','textbox');outer.innerHTML='<div contenteditable=true role=textbox>nested composer</div>';draft.after(outer);
await wait();assert(api().composerSelection().element===outer&&api().observe().state==='idle','nested editor is one editing root');
const extra=document.createElement('textarea');document.body.append(extra);await wait();
assert(api().observe().reason==='AMBIGUOUS_COMPOSER','independent composers fail closed');
assert(card()?.matches('[data-twos-native-card]')&&card().querySelector('[data-twos-primary]').hidden&&card().textContent.includes('ambiguous'),'R4 unknown hides Send but retains precise reason');
assert(api().latest().state==='unknown','unknown cannot freeze partial answer');
const stop=document.createElement('button');stop.setAttribute('aria-label','Stop');document.body.append(stop);await wait();
assert(api().observe().state==='running','real generation signal outranks missing/ambiguous composer');
assert(card().querySelector('[data-twos-primary]').hidden,'R4 stream has no Send card');
// A webpage's synthetic click cannot acquire the native shared-session Stop handler.
stop.click();stop.remove();extra.remove();outer.remove();draft.hidden=false;await wait();
assert(!card().querySelector('button').disabled,'ready transition restores entry');
const user=document.createElement('div');user.dataset.messageAuthorRole='user';user.textContent='NEW CURRENT QUESTION';document.body.append(user);await wait();
assert(api().latest().reason==='LATEST_USER_AWAITS_REPLY','old topic cannot substitute for new pending response');
assert(card().querySelector('[data-twos-primary]').hidden,'old topic cannot supply a Send action while pending');user.remove();
// Framework remount + target change must yield one card for the same final answer.
const old=document.getElementById('answer'),replacement=old.cloneNode(true);old.replaceWith(replacement);await wait();
window.twosHandoffTarget({provider:'Claude',binding:'TEST-EXACT-ROUTE'});await wait();
assert(document.querySelectorAll('[data-twos-native-card]').length===1,'SPA remount no duplicate cards');
assert(card().querySelector('button').textContent==='Send to Claude','current peer label');
assert(api().latest().text===original,'card UI never contaminates reply body');
// A new host revision cannot turn a confirmed receipt into another Send.
window.twosHandoffTarget({provider:'Claude',binding:'new-revision|1|Claude|https://claude.ai/chat/test'});
const bytes=new TextEncoder().encode(original),hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
await window.twosHandoffUpdate({id:'TEST-RECEIPT',source:location.href,message:api().latest().message,hash,provider:'Claude',state:'sent',binding:'old-revision|1|Claude|https://claude.ai/chat/test'});await wait();
assert(card().querySelector('[data-twos-primary]').hidden&&card().textContent.includes('Sent to Claude'),'confirmed delivery survives route revision without Send');
window.twosHandoffTarget({provider:'Claude',binding:'new-revision|1|Claude|https://claude.ai/chat/different'});await wait();
assert(!card().querySelector('[data-twos-primary]').hidden,'explicit different destination permits new handoff');
// Screen-reader speaker headings inside one outer article are separate turns.
const shared=document.createElement('article');shared.innerHTML='<h4 style="position:absolute;width:0;height:0;overflow:hidden">你说：You</h4><p>TEST FIRST</p><h4 style="position:absolute;width:0;height:0;overflow:hidden">ChatGPT 说：ChatGPT</h4><div data-markdown-text-style="assistant-message" id="plain-one">Plain reply one</div><h4 style="position:absolute;width:0;height:0;overflow:hidden">你说：You</h4><p>TEST SECOND</p><h4 style="position:absolute;width:0;height:0;overflow:hidden">ChatGPT 说：ChatGPT</h4><div data-markdown-text-style="assistant-message" id="plain-two">Plain reply two</div>';document.body.append(shared);await wait();
assert(api().replies().length===3,'one shared article does not merge multiple complete turns');
assert(document.querySelectorAll('[data-twos-native-card]').length===1&&document.getElementById('plain-two').nextElementSibling.matches('[data-twos-native-card]'),'R4 only latest reply has an action area');
assert(api().latest().text==='Plain reply two','canonical latest preserves topic boundary');
// Stopping ChatGPT before a final answer must not reuse an older reply.
const pending=document.createElement('div');pending.dataset.userMessageBubble='true';pending.textContent='TEST STOP BEFORE ANSWER';document.body.append(pending);
const stopped=document.createElement('div');stopped.textContent='已停止思考';document.body.append(stopped);await wait();
assert(api().observe().state==='idle'&&api().latest().reason==='REPLY_INTERRUPTED','native stopped thinking is idle but not a completed answer');
assert(api().stoppedAfter(pending),'exact current turn native stop is observed');
assert(api().replyState(document.getElementById('plain-two')).complete,'an explicitly selected earlier complete answer keeps its own identity');
const nextUser=document.createElement('div');nextUser.dataset.userMessageBubble='true';nextUser.textContent='TEST NEXT QUESTION';document.body.append(nextUser);
assert(!api().stoppedAfter(nextUser),'older stop does not cancel a later question');
pending.remove();stopped.remove();nextUser.remove();
// Claude's native interrupted marker is not a complete answer. A quotation in
// standard Markdown is ordinary content, not a provider state or stop command.
document.querySelectorAll('article').forEach(e=>e.remove());
document.documentElement.dataset.twosFixtureProvider='Claude';
const claude=document.createElement('div');claude.dataset.isStreaming='false';claude.innerHTML='<div class="standard-markdown"><p>Claude 的回复已中断。</p></div>';document.body.append(claude);await wait();
assert(api().replyState(claude).complete,'quoted interruption is normal answer text');
claude.insertAdjacentHTML('beforeend','<div role="status"><span>Claude 的回复已中断。</span></div>');await wait();
assert(api().latest().reason==='REPLY_INTERRUPTED','native interruption blocks latest');
assert(!api().replyState(claude).complete&&claude.nextElementSibling.querySelector('[data-twos-primary]').hidden,'R4 interrupted partial has no Send button');
const selection=getSelection(),range=document.createRange();range.selectNodeContents(claude.querySelector('p'));selection.removeAllRanges();selection.addRange(range);
assert((await api().selectedOrLatest()).state==='unknown','selection cannot bypass interrupted reply boundary');selection.removeAllRanges();

window.twosHandoffAutoState({enabled:true,supported:true,pending:false,state:'running',count:3,reason:''});await wait();
assert(!document.querySelector('[data-twos-primary]').hidden&&document.querySelector('[data-twos-primary]').textContent==='Stop auto-send','Stop stays in the same action area even when no complete reply');
assert(document.querySelector('[data-twos-automatic]').checked,'host state mirrors checkbox');
window.twosHandoffLanguage(true);await wait();
assert(document.querySelector('[data-twos-primary]').textContent==='停止自动发送','Chinese stop remains accessible');
window.twosHandoffAutoState({enabled:false,supported:true,pending:false,state:'stopped',reason:''});await wait();
assert(!document.querySelector('[data-twos-automatic]').checked&&document.querySelector('[data-twos-primary]').hidden,'stopping restores incomplete state without send');
return 'R3_DOM_PASS';
