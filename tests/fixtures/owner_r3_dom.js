// TEST/FIXTURE ONLY. No external connection, credentials or model request.
const assert=(x,m)=>{if(!x)throw Error(m)},wait=()=>new Promise(r=>setTimeout(r,500));
const api=()=>window.twosProviderDOM,card=()=>document.getElementById('answer').nextElementSibling;
await wait();
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
assert(card()?.matches('[data-twos-native-card]')&&card().querySelector('button').disabled&&card().textContent.includes('More than one'),'unknown preserves visible disabled entry and reason');
assert(api().latest().state==='unknown','unknown cannot freeze partial answer');
const stop=document.createElement('button');stop.setAttribute('aria-label','Stop');document.body.append(stop);await wait();
assert(api().observe().state==='running','real generation signal outranks missing/ambiguous composer');
assert(card().querySelector('button').disabled,'stream cannot be dispatched');
// A webpage's synthetic click cannot acquire the native shared-session Stop handler.
stop.click();stop.remove();extra.remove();outer.remove();draft.hidden=false;await wait();
assert(!card().querySelector('button').disabled,'ready transition restores entry');
const user=document.createElement('div');user.dataset.messageAuthorRole='user';user.textContent='NEW CURRENT QUESTION';document.body.append(user);await wait();
assert(api().latest().reason==='LATEST_USER_AWAITS_REPLY','old topic cannot substitute for new pending response');
assert(card().querySelector('button').disabled,'old topic remains visible but unavailable while pending');user.remove();
// Framework remount + target change must yield one card for the same final answer.
const old=document.getElementById('answer'),replacement=old.cloneNode(true);old.replaceWith(replacement);await wait();
window.twosHandoffTarget({provider:'Claude',binding:'TEST-EXACT-ROUTE'});await wait();
assert(document.querySelectorAll('[data-twos-native-card]').length===1,'SPA remount no duplicate cards');
assert(card().querySelector('button').textContent==='Send to Claude','current peer label');
assert(api().latest().text===original,'card UI never contaminates reply body');
// Screen-reader speaker headings inside one outer article are separate turns.
const shared=document.createElement('article');shared.innerHTML='<h4 style="position:absolute;width:0;height:0;overflow:hidden">你说：You</h4><p>TEST FIRST</p><h4 style="position:absolute;width:0;height:0;overflow:hidden">ChatGPT 说：ChatGPT</h4><div data-markdown-text-style="assistant-message" id="plain-one">Plain reply one</div><h4 style="position:absolute;width:0;height:0;overflow:hidden">你说：You</h4><p>TEST SECOND</p><h4 style="position:absolute;width:0;height:0;overflow:hidden">ChatGPT 说：ChatGPT</h4><div data-markdown-text-style="assistant-message" id="plain-two">Plain reply two</div>';document.body.append(shared);await wait();
assert(api().replies().length===3,'one shared article does not merge multiple complete turns');
for(const id of ['plain-one','plain-two'])assert(document.getElementById(id).nextElementSibling.matches('[data-twos-native-card]'),'each complete reply retains its card');
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
assert(!api().replyState(claude).complete&&claude.nextElementSibling.querySelector('button').disabled,'interrupted partial retains disabled card');
const selection=getSelection(),range=document.createRange();range.selectNodeContents(claude.querySelector('p'));selection.removeAllRanges();selection.addRange(range);
assert(api().selectedOrLatest().state==='unknown','selection cannot bypass interrupted reply boundary');selection.removeAllRanges();
return 'R3_DOM_PASS';
