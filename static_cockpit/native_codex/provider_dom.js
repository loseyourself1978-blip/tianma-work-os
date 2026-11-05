// Public rendered UI only, in TWOS's isolated content world. Observation never
// returns conversation text. Explicit handoff alone may read one final answer.
(() => {
 'use strict';
 const hosts={'chatgpt.com':'ChatGPT','claude.ai':'Claude','chat.deepseek.com':'DeepSeek'};
 const provider=hosts[location.hostname];
 const visible=e=>Boolean(e?.getClientRects().length)&&getComputedStyle(e).visibility!=='hidden'&&!e.closest('[hidden],[inert],[aria-hidden="true"]');
 const excluded='nav,aside,[role=menu],[data-twos-native-card]';
 const all=s=>[...document.querySelectorAll(s)].filter(e=>visible(e)&&!e.closest(excluded));
 const selectedProvider=()=>provider||(location.hostname==='127.0.0.1'?document.documentElement.dataset.twosFixtureProvider:null);
 const assistant='[data-message-author-role="assistant"],[data-markdown-text-style="assistant-message"]';
 const history=assistant+',[data-message-author-role="user"],[data-testid="user-message"],[data-user-message-bubble],[data-role="user"],[data-role="assistant"],[data-message-role="user"],[data-message-role="assistant"],[data-is-streaming],.font-claude-response,.ds-message';
 const speaker=e=>/^(?:(?:You said|你说)[:：]?\s*)+(?:You)?$/i.test(e.textContent.trim())?'user':/^(?:(?:ChatGPT said|ChatGPT 说)[:：]?\s*)+(?:ChatGPT)?$/i.test(e.textContent.trim())?'assistant':null;
 const headings=()=>[...document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role=heading]')].filter(e=>speaker(e)&&!e.closest(excluded+','+history+',textarea,[contenteditable=true],[hidden],[inert],[aria-hidden="true"]')&&(visible(e)||visible(e.parentElement)));
 const sourceKey=e=>e.closest('[data-message-id]')?.getAttribute('data-message-id')||e.closest('[data-testid^="conversation-turn-"]')?.getAttribute('data-testid')||'';
 const replies=()=>{
  const p=selectedProvider(),s=p==='ChatGPT'?assistant:p==='Claude'?'[data-is-streaming],.font-claude-response':p==='DeepSeek'?'[data-role="assistant"],[data-message-role="assistant"],.ds-message .ds-markdown':assistant;
  const nodes=all(s).filter(e=>!e.parentElement?.closest(s));
  if(p&&p!=='ChatGPT')return nodes;
  const groups=new Map(),hs=headings();
  for(const e of nodes){
   const preceding=hs.filter(h=>Boolean(h.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING)).at(-1);
   // A shared outer article can contain several turns. Prefer each public
   // speaker heading (including visually hidden accessibility headings) before
   // the generic article, while retaining within-turn summary grouping.
   const group=preceding||sourceKey(e)||e.closest('article,[data-testid^="conversation-turn-"]')||'latest';
   groups.set(group,e);
  }
  return [...groups.values()];
 };
 // One resolver is shared by observation, message cards, uploads and dispatch.
 // Exclude hidden compatibility fields and reply/canvas editors. Nested editor
 // wrappers are one editing root; two independent roots remain ambiguous.
 function composerSelection(){
  const candidates=all('textarea,#prompt-textarea,[contenteditable=true][role=textbox],.tiptap[contenteditable=true]').filter(e=>!e.disabled&&!e.readOnly&&!e.closest(history+',[role=dialog]'));
  const roots=candidates.filter(e=>!candidates.some(parent=>parent!==e&&parent.contains(e)));
  const known=roots.filter(e=>e.id==='prompt-textarea'||e.querySelector('#prompt-textarea')||e.matches('[data-testid="chat-input"],[data-testid="composer-input"]'));
  const fields=known.length===1?known:roots;
  return {element:fields.length===1?fields[0]:null,count:roots.length,reason:fields.length===1?'COMPOSER_IDENTIFIED':roots.length?'AMBIGUOUS_COMPOSER':'INPUT_UNAVAILABLE'};
 }
 const input=()=>composerSelection().element;
 const semanticStop=e=>visible(e)&&!e.closest(excluded+','+history)&&!e.disabled&&(e.matches('[data-testid="stop-button"]')||/^(stop(?: generating| response)?|停止(?:生成|回复)?)$/i.test(e.getAttribute('aria-label')||e.getAttribute('title')||e.textContent.trim()));
 const isStop=e=>semanticStop(e)||e===deepSeekControl('stop',true);
 const stop=()=>all('button,[role=button]').some(semanticStop)||Boolean(deepSeekControl('stop',true));
 const users=()=>all('[data-message-author-role="user"],[data-testid="user-message"],[data-markdown-text-style="user-message"],[data-user-message-bubble],[data-role="user"],[data-message-role="user"],.ds-collapsible-text').concat(headings().filter(e=>speaker(e)==='user')).filter(e=>!e.closest(assistant));
 const hasLaterUser=reply=>users().some(e=>Boolean(reply.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING));
 const stoppedAfter=(anchor,before=null)=>selectedProvider()==='ChatGPT'&&Boolean(anchor)&&all('span,div,p').some(e=>
  !e.children.length&&!e.closest(history+',[data-markdown-text-style],.standard-markdown,blockquote,pre,code,textarea,[contenteditable=true]')&&
  /^(?:Stopped thinking|已停止思考)[。.]?$/i.test(e.textContent.trim())&&Boolean(anchor.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING)&&
  (!before||Boolean(e.compareDocumentPosition(before)&Node.DOCUMENT_POSITION_FOLLOWING)));
 const latestUser=()=>users().sort((a,b)=>a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING?-1:1).at(-1);
 // One scoped control resolver feeds activity, native Stop and dispatch.
 // Prefer accessible semantics. The two unlabeled 16px controls below were
 // observed in the isolated DeepSeek client on 2026-11-05; an unknown icon
 // stays unknown. A missing Send icon is never proof of generation/completion.
 const deepSeekShapes={send:"M8.3125 0.980206C8.66767 1.05312 8.97902 1.2042 9.2627 1.43235C9.48724 1.613 9.73029 1.85795 9.97949 2.10716L14.707 6.8347L13.293 8.24876L9 3.95579V15.0417H7V3.95579L2.70703 8.24876L1.29297 6.8347L6.02051 2.10716C6.26971 1.85795 6.51277 1.613 6.7373 1.43235C6.97662 1.23988 7.28445 1.04404 7.6875 0.980206C7.8973 0.947029 8.1031 0.955183 8.3125 0.980206Z",stop:"M2 4.88C2 3.68009 2 3.08013 2.30557 2.65954C2.40426 2.52371 2.52371 2.40426 2.65954 2.30557C3.08013 2 3.68009 2 4.88 2H11.12C12.3199 2 12.9199 2 13.3405 2.30557C13.4763 2.40426 13.5957 2.52371 13.6944 2.65954C14 3.08013 14 3.68009 14 4.88V11.12C14 12.3199 14 12.9199 13.6944 13.3405C13.5957 13.4763 13.4763 13.5957 13.3405 13.6944C12.9199 14 12.3199 14 11.12 14H4.88C3.68009 14 3.08013 14 2.65954 13.6944C2.52371 13.5957 2.40426 13.4763 2.30557 13.3405C2 12.9199 2 12.3199 2 11.12V4.88Z"};
 function deepSeekControl(kind,requireEnabled=false){
  if(selectedProvider()!=='DeepSeek')return null;
  let root=input()?.parentElement;
  for(let n=0;root&&root!==document.body&&n<5;n++,root=root.parentElement){
   if(root.querySelector(history))break;
   const controls=[...root.querySelectorAll('button,[role=button]')].filter(e=>visible(e)&&!e.closest(excluded+','+history));
   const recognized=controls.map(e=>{
    const label=e.getAttribute('aria-label')||e.getAttribute('title')||e.textContent.trim();
    if(/^(?:Send(?: message| prompt)?|发送(?:消息|提示)?)$/i.test(label)||e.matches('[data-testid="send-button"],[data-testid="chat-input-send"]'))return {element:e,kind:'send'};
    if(/^(?:Stop(?: generating| response)?|停止(?:生成|回复)?)$/i.test(label)||e.matches('[data-testid="stop-button"]'))return {element:e,kind:'stop'};
    if(!e.matches('.ds-button--primary.ds-button--circle'))return null;
    const svg=e.querySelector('svg');if(!svg || !(svg.getAttribute('viewBox')==='0 0 16 16'||(!svg.hasAttribute('viewBox')&&svg.getAttribute('width')==='16'&&svg.getAttribute('height')==='16')) || svg.querySelectorAll('path').length!==1)return {element:e,kind:'unknown'};
    const path=svg.querySelector('path').getAttribute('d');
    return {element:e,kind:Object.keys(deepSeekShapes).find(k=>deepSeekShapes[k]===path)||'unknown'};
   }).filter(Boolean);
   // Do not choose among duplicate, contradictory or unrecognized primary controls.
   if(recognized.length){
    if(recognized.length!==1||recognized[0].kind!==kind)return null;
    const e=recognized[0].element;
    if(requireEnabled&&(e.disabled||e.getAttribute('aria-disabled')==='true'||e.classList.contains('ds-button--disabled')))return null;
    return e;
   }
  }return null;
 }
 function observe(){
  if(!selectedProvider())return {state:'unknown',reason:'UNSUPPORTED_PROVIDER'};
  if(document.querySelector('iframe[src*="challenges.cloudflare.com"],#challenge-running,#challenge-stage')||all('h1,h2').some(e=>/security verification|verify you are human|正在进行安全验证|验证您是真人/i.test(e.textContent)))return {state:'waiting_user',reason:'VERIFICATION'};
  // Generation is observable even if the website temporarily disables or
  // remounts its composer. An ambiguous input must not hide a real Stop signal.
  const last=replies().at(-1),stream=stop()||Boolean(last&&(last.matches('[data-is-streaming="true"]')||last.querySelector('[data-is-streaming="true"]')));
  const selection=composerSelection(),facts={composerCandidates:selection.count};
  if(stream)return {state:'running',reason:'VISIBLE_GENERATION_CONTROL',...facts};
  if(!selection.element)return {state:all('button,a').some(e=>/^(log in|sign in|登录|登入)$/i.test(e.textContent.trim()))?'waiting_user':'unknown',reason:selection.reason,...facts};
  if(selectedProvider()==='DeepSeek'&&!deepSeekControl('send'))return {state:'unknown',reason:'GENERATION_STATE_UNCONFIRMED',...facts};
  if(stoppedAfter(latestUser()))return {state:'idle',reason:'NATIVE_GENERATION_INTERRUPTED',...facts};
  if(last&&hasLaterUser(last))return {state:'unknown',reason:'LATEST_USER_AWAITS_REPLY',...facts};
  return {state:'idle',reason:'VISIBLE_IDLE_COMPOSER',...facts};
 }
 function replyState(reply){
  if(!reply?.isConnected||!replies().includes(reply))return {complete:false,reason:'REPLY_REPLACED'};
  const status=observe();
  if(reply.matches('[data-is-streaming="true"]')||reply.querySelector('[data-is-streaming="true"]'))return {complete:false,reason:'REPLY_STREAMING'};
  const nextUser=users().filter(e=>Boolean(reply.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING)).sort((a,b)=>a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING?-1:1)[0];
  if(interrupted(reply)||stoppedAfter(reply,nextUser))return {complete:false,reason:'REPLY_INTERRUPTED'};
  if(status.state!=='idle')return {complete:false,reason:status.reason};
  if(!text(reply).trim())return {complete:false,reason:'EMPTY_REPLY'};
  return {complete:true,reason:'COMPLETE_REPLY'};
 }
 function interrupted(reply){
  if(!reply)return false;
  if(selectedProvider()==='DeepSeek'){
   // Only provider chrome in this exact message can mark a partial answer.
   // Never interpret quoted "Stopped" or a code example inside Markdown.
   const message=reply.closest('.ds-message');
   if(!message)return false;
   if([...message.querySelectorAll('*')].some(e=>visible(e)&&!e.closest('.ds-markdown,[data-twos-native-card],blockquote,pre,code')&&
    !e.children.length&&/^(?:已停止|Stopped|Response stopped)[。.]?$/i.test(e.textContent.trim())))return true;
   // DeepSeek puts Continue generating in a sibling toolbar, outside
   // .ds-message, when the answer (rather than thinking) was interrupted.
   const nextUser=users().filter(e=>Boolean(reply.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING))
    .sort((a,b)=>a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING?-1:1)[0];
   return all('button,[role=button]').some(e=>e.classList.contains('ds-button')&&!e.closest('.ds-markdown,blockquote,pre,code')&&
    /^(?:继续生成|Continue generating)[。.]?$/i.test(e.textContent.trim())&&
    Boolean(reply.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING)&&
    (!nextUser||Boolean(e.compareDocumentPosition(nextUser)&Node.DOCUMENT_POSITION_FOLLOWING)));
  }
  if(selectedProvider()!=='Claude')return false;
  // Provider-owned interruption UI, outside the answer Markdown. A quotation
  // inside an answer must never be interpreted as a stop command or terminal.
  return [...reply.querySelectorAll('*')].some(e=>visible(e)&&!e.closest('.standard-markdown,[data-twos-native-card],button,[role=button]')&&
   !e.children.length&&/^(?:Claude(?:'s|’s) response was interrupted\.?|Claude 的回复已中断[。.]?)$/i.test(e.textContent.trim()));
 }
 function userText(user){
  if(speaker(user)!=='user')return text(user);
  const hs=headings(),next=hs[hs.indexOf(user)+1],range=document.createRange();range.setStartAfter(user);
  if(next)range.setEndBefore(next);else range.setEnd(document.body,document.body.childNodes.length);
  const fragment=range.cloneContents();
  fragment.querySelectorAll(excluded+','+assistant+',textarea,[contenteditable=true],form,button,[role=button]').forEach(e=>e.remove());
  return fragment.textContent||'';
 }
 // Public message IDs remain preferred. Without one, hash only this reply and
 // its preceding user turn, never its position in a virtualized history list.
 // Identical question/answer pairs without public IDs are intentionally
 // indistinguishable: reconcile instead of risking another send.
 const identityCache=window.twosReplyIdentityCache ||= new Map();
 function identityEntry(reply){
  const user=users().filter(e=>Boolean(e.compareDocumentPosition(reply)&Node.DOCUMENT_POSITION_FOLLOWING))
   .sort((a,b)=>a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING?-1:1).at(-1);
  const body=text(reply),question=user?userText(user):'';
  if(new TextEncoder().encode(body).length>200000||new TextEncoder().encode(question).length>200000)return null;
  const key=JSON.stringify([selectedProvider(),user?sourceKey(user):'',question,body]);
  let entry=identityCache.get(key);if(entry)return entry;
  entry={value:'',pending:null};identityCache.set(key,entry);
  if(identityCache.size>32)identityCache.delete(identityCache.keys().next().value);
  entry.pending=crypto.subtle.digest('SHA-256',new TextEncoder().encode(key)).then(bytes=>{
   entry.value='rendered-turn-v2:'+[...new Uint8Array(bytes)].map(x=>x.toString(16).padStart(2,'0')).join('');
   window.twosHandoffIdentityReady?.();
  }).catch(()=>{});
  return entry;
 }
 function identity(reply){return sourceKey(reply)||identityEntry(reply)?.value||'';}
 async function resolvedLatest(){
  const result=latest();
  if(result.reason==='REPLY_IDENTITY_PENDING')await identityEntry(replies().at(-1))?.pending;
  return latest();
 }
 function text(el){
  // Current Claude puts its public progress/status line alongside, not inside,
  // the final standard-markdown body. Read that body without forwarding status
  // placeholders or duplicate accessibility announcements. Keep the outer
  // message for streaming/identity checks and card placement.
  if(selectedProvider()==='Claude'){
   const bodies=[...el.querySelectorAll('.standard-markdown')].filter(e=>visible(e)&&!e.closest('[class~="group/status"],[role=status],[data-twos-native-card]')&&!e.parentElement?.closest('.standard-markdown'));
   if(bodies.length)return bodies.map(body=>textBody(body)).join('\n\n');
  }
  return textBody(el);
 }
 function textBody(el){
  // Inline file references are answer content, not toolbar controls. Preserve
  // their visible name without activating the preview or exporting file bytes.
  const fileReference=e=>e.closest('p,td,li')&&/^(?:打开 .+ 的预览|Open .+ preview)$/i.test(e.getAttribute('aria-label')||'');
  const controls=[...[...el.querySelectorAll('button,[role=button],[role=toolbar],time,[data-twos-native-card]')].filter(e=>!fileReference(e)),
   ...[...el.querySelectorAll('h3,[role=heading]')].filter(e=>/^(Claude (?:已回复|说|said|replied)[:：])/.test(e.textContent.trim()))
  ].map(e=>[e,e.getAttribute('style')]);
  try{controls.forEach(([e,s])=>e.setAttribute('style',(s||'')+';display:none!important'));return el.innerText||'';}
  finally{controls.forEach(([e,s])=>s===null?e.removeAttribute('style'):e.setAttribute('style',s));}
 }
 function latest(){
  const status=observe();if(status.state!=='idle')return status;
  if(stoppedAfter(latestUser()))return {state:'unknown',reason:'REPLY_INTERRUPTED'};
  const reply=replies().at(-1);if(!reply)return {state:'unknown',reason:'NO_COMPLETE_REPLY'};
  const eligibility=replyState(reply);if(!eligibility.complete)return {state:'unknown',reason:eligibility.reason};
  const body=text(reply);if(!body.trim())return {state:'unknown',reason:'EMPTY_REPLY'};
  if(new TextEncoder().encode(body).length>200000)return {state:'unsupported',reason:'REPLY_TOO_LARGE'};
  // No sidebars, unrelated selection, quoted prior card or partial stream.
  const message=identity(reply);if(!message)return {state:'unknown',reason:'REPLY_IDENTITY_PENDING'};
  return {state:'reply',text:body,message};
 }
 async function seedSnapshot(){
  const result=await resolvedLatest(),user=latestUser();
  window.twosSeedDocumentID ||= crypto.randomUUID();result.documentID=window.twosSeedDocumentID;
  if(user){
   const body=userText(user);
   if(new TextEncoder().encode(body).length>200000)return {state:'unsupported',reason:'CURRENT_MESSAGE_TOO_LARGE'};
   const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(body)))].map(x=>x.toString(16).padStart(2,'0')).join('');
   if(latestUser()!==user)return {state:'unknown',reason:'SOURCE_TURN_CHANGED'};
   result.userAnchor=(sourceKey(user)||'rendered-user-v2')+':'+hash;
  }
  const current=latest();
  if(current.state!==result.state||current.message!==result.message||current.text!==result.text)return {state:'unknown',reason:'SOURCE_TURN_CHANGED'};
  return result;
 }
 function navigationSafety(){
  const status=observe(),field=input();
  if(status.state!=='idle'||!field)return {state:status.state,hasDraft:true};
  if((field instanceof HTMLTextAreaElement?field.value:field.innerText).trim())return {state:'idle',hasDraft:true};
  // Only inspect the current composer, not files in conversation history.
  let root=field.parentElement;
  for(let depth=0;root&&root!==document.body&&depth<8;root=root.parentElement,depth++){
   if(root.querySelector('[data-message-author-role],[data-testid="user-message"],[data-is-streaming],.font-claude-response,.ds-message'))break;
   if([...root.querySelectorAll('button,[role=button],[data-testid*=attachment],[data-testid*=file-upload]')].some(e=>visible(e)&&(e.matches('[data-testid*=attachment],[data-testid*=file-upload]')||/^(Remove(?: attachment| file)?|移除(?:附件)?)\s+/i.test(e.getAttribute('aria-label')||'')||/\.[a-z0-9]{1,10}$/i.test(e.getAttribute('aria-label')||''))))return {state:'idle',hasDraft:true};
  }
  return {state:'idle',hasDraft:false};
 }
 async function selectedOrLatest(){
  const selection=getSelection();
  if(selection?.rangeCount===1&&!selection.isCollapsed){
   const range=selection.getRangeAt(0),node=range.commonAncestorContainer;
   const element=node.nodeType===Node.ELEMENT_NODE?node:node.parentElement;
   const body=selection.toString();
   const safe=element&&!element.closest('nav,aside,[role=dialog],[role=menu],[data-twos-native-card],textarea,[contenteditable=true]');
   const inReply=replies().some(e=>e.contains(range.startContainer)&&e.contains(range.endContainer)&&replyState(e).complete);
   if(safe&&body.trim()&&new TextEncoder().encode(body).length<=200000&&(!selectedProvider()||(inReply&&observe().state==='idle'))){
    return {state:'reply',text:body,message:'selected-content'};
   }
   return {state:'unknown',reason:'SELECT_A_COMPLETE_REPLY_NOT_A_FLOATING_CONTROL'};
  }
  return resolvedLatest();
 }
 window.twosProviderDOM={observe,latest,resolvedLatest,seedSnapshot,selectedOrLatest,replies,text,navigationSafety,composerSelection,replyState,identity,isStop,deepSeekControl,interrupted,speaker,headings,stoppedAfter};
 // Only a genuine user activation of a recognized native Stop control signals
 // the host. Isolated-world handler + native frame/origin checks stay in force.
 if(!window.twosNativeStopListener){
  window.twosNativeStopListener=true;
  const revokeFromNativeStop=event=>{
   if(event.type==='keydown'&&!['Enter',' '].includes(event.key))return;
   if(event.type==='pointerdown'&&event.button!==0)return;
   const control=event.target instanceof Element?event.target.closest('button,[role=button]'):null;
   if(!event.isTrusted||!control||!window.twosProviderDOM?.isStop(control))return;
   window.twosTransferLease=crypto.randomUUID();
   window.webkit?.messageHandlers?.twosHandoff?.postMessage({action:'nativeStop',source:location.href});
  };
  // Capture intent before the provider disables/replaces its Stop on release.
  // Click remains for accessibility activation. Repeated revocation is safe;
  // none of these events grant sending, execution or approval permission.
  for(const type of ['pointerdown','keydown','click'])document.addEventListener(type,revokeFromNativeStop,true);
 }

})();
