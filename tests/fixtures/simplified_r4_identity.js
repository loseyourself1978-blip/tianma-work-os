// SIMULATED / TEST ONLY: virtualized public DOM, no provider/model request.
const assert=(x,m)=>{if(!x)throw Error(m)},wait=()=>new Promise(r=>setTimeout(r,800));
const api=()=>window.twosProviderDOM,primary=()=>document.querySelector('[data-twos-primary]');
document.querySelector('article').remove();
const turn=document.createElement('article');
turn.innerHTML='<h4>You said:</h4><p>TEST CURRENT QUESTION</p><h4>ChatGPT said:</h4><div data-markdown-text-style="assistant-message" id="answer">TEST COMPLETE ANSWER</div>';
document.body.append(turn);await wait();
const first=await api().seedSnapshot();
assert(first.state==='reply'&&first.message.startsWith('rendered-turn-v2:'),'stable content-anchored fallback');
const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(first.text)))].map(x=>x.toString(16).padStart(2,'0')).join('');
window.twosHandoffTarget({provider:'Claude',binding:'r1|1|Claude|https://claude.ai/chat/TEST'});
await window.twosHandoffUpdate({id:'TEST-STABLE',source:location.href,message:first.message,hash,provider:'Claude',state:'sent',binding:'r0|1|Claude|https://claude.ai/chat/TEST'});await wait();
assert(primary().hidden,'sent reply has no duplicate Send');
const older=document.createElement('article');older.innerHTML='<h4>You said:</h4><p>TEST OLDER QUESTION</p><h4>ChatGPT said:</h4><div data-markdown-text-style="assistant-message">TEST OLDER ANSWER</div>';
turn.before(older);const remount=turn.cloneNode(true);turn.replaceWith(remount);await wait();
const restored=await api().seedSnapshot();
assert(document.querySelectorAll('[data-twos-native-card]').length===1,'remounted provider subtree cannot retain inert duplicate action');
assert(restored.message===first.message&&restored.userAnchor===first.userAnchor,'history hydration/remount cannot renumber selected turn');
assert(primary().hidden&&document.querySelector('[data-twos-native-card]').textContent.includes('Sent to Claude'),'receipt remains attached after hydration');
// Same answer for a different current question must not inherit that receipt.
const next=document.createElement('article');next.innerHTML='<h4>You said:</h4><p>TEST DIFFERENT QUESTION</p><h4>ChatGPT said:</h4><div data-markdown-text-style="assistant-message">TEST COMPLETE ANSWER</div>';
document.body.append(next);await wait();const different=await api().seedSnapshot();
assert(different.message!==first.message&&different.userAnchor!==first.userAnchor,'different user turn has different identity');
assert(!primary().hidden,'new question does not inherit stable receipt');
// Legacy position-only receipts cannot prove identity after restart. They
// block potential duplicates, but must not claim this new message was sent.
await window.twosHandoffUpdate({id:'TEST-LEGACY',source:location.href,message:'rendered-assistant-0',hash,provider:'Claude',state:'sent',binding:'old|1|Claude|https://claude.ai/chat/TEST'});await wait();
const area=document.querySelector('[data-twos-native-card]');
assert(primary().hidden&&area.textContent.includes('message identity needs verification'),'legacy ambiguity is explicit and fail-closed');
assert(!area.querySelector('[role=status]').textContent.includes('Sent to Claude'),'legacy hash match is not identity proof');
// Existing node text changes invalidate its cached hash and action identity.
next.querySelector('[data-markdown-text-style]').textContent='TEST REVISED ANSWER';await wait();
const revised=await api().resolvedLatest();await wait();
assert(revised.message!==different.message&&!primary().hidden,'in-place content revision gets a new complete action');
window.twosHandoffLanguage(true);await wait();
assert(primary().textContent==='发送到 Claude','Chinese action remains available');
return 'R3_DOM_PASS';
