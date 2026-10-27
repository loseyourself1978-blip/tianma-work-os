// Named isolated WKContentWorld, invoked by a confirmed native transfer only.
// Uses the site's visible composer and send control. No fetch, private APIs,
// cookies, background-history extraction, synthetic keys or provider fallback.
return await (async () => {
 'use strict';
 const clean=raw=>{const u=new URL(raw);u.search='';u.hash='';return u.href;};
 const original=clean(request.targetURL), origin=new URL(original).origin;
 const provider=request.provider;
 const host={ChatGPT:'chatgpt.com',DeepSeek:'chat.deepseek.com',Claude:'claude.ai'}[provider];
 const localFixture=location.hostname==='127.0.0.1'&&new URL(original).origin===location.origin;
 if((location.hostname!==host&&!localFixture)||location.origin!==origin||(!request.inspectOnly&&clean(location.href)!==original))return {state:request.inspectOnly?'unknown':'target_changed'};
 const lease=window.twosTransferLease;
 const same=()=>window.twosTransferLease===lease&&location.origin===origin;
 const visible=el=>Boolean(el?.getClientRects().length)&&getComputedStyle(el).visibility!=='hidden';
 const normalize=s=>(s||'').replace(/\r\n?/g,'\n').trim();
 const plain=el=>{const copy=el.cloneNode(true);copy.querySelectorAll('button,[role=button],[data-twos-native-card],textarea,[contenteditable=true]').forEach(x=>x.remove());return copy.textContent||'';};
 // Inspect challenge/login before any DOM mutation. Do not touch the challenge frame.
 const heading=[...document.querySelectorAll('h1,h2')].filter(visible).map(x=>x.textContent).join(' ');
 if(document.querySelector('iframe[src*="challenges.cloudflare.com"],#challenge-running,#challenge-stage')||/security verification|verify you are human|正在进行安全验证|验证您是真人/i.test(heading))return {state:'verification'};
 const fields=[...document.querySelectorAll('textarea,#prompt-textarea,[contenteditable=true][role=textbox],.tiptap[contenteditable=true]')].filter(e=>visible(e)&&!e.disabled&&!e.readOnly&&!e.closest('[data-twos-native-card],[data-message-author-role],.ds-markdown'));
 if(fields.length!==1){
  const login=[...document.querySelectorAll('button,a')].filter(visible).some(e=>/^(log in|sign in|登录|登入)$/i.test(e.textContent.trim()));
  return {state:login?'login':'not_loaded'};
 }
 if(request.readinessOnly)return {state:'input_ready'};
 const input=fields[0],value=()=>input instanceof HTMLTextAreaElement?input.value:input.innerText;
 const prompt='[TWOS handoff '+request.id+']\n'+request.text;
 const deepSeekArrow="M8.3125 0.980206C8.66767 1.05312 8.97902 1.2042 9.2627 1.43235C9.48724 1.613 9.73029 1.85795 9.97949 2.10716L14.707 6.8347L13.293 8.24876L9 3.95579V15.0417H7V3.95579L2.70703 8.24876L1.29297 6.8347L6.02051 2.10716C6.26971 1.85795 6.51277 1.613 6.7373 1.43235C6.97662 1.23988 7.28445 1.04404 7.6875 0.980206C7.8973 0.947029 8.1031 0.955183 8.3125 0.980206Z";
 const deepSeekSend=(requireEnabled=true)=>{
  if(provider!=='DeepSeek'||(location.hostname!=='chat.deepseek.com'&&!localFixture))return null;
  let parent=input.parentElement;for(let n=0;parent&&n<5;n++,parent=parent.parentElement){
   const candidates=[...parent.querySelectorAll('[role=button].ds-button--primary.ds-button--circle')].filter(e=>visible(e)&&(!requireEnabled||!e.classList.contains('ds-button--disabled'))&&e.querySelector('svg path')?.getAttribute('d')===deepSeekArrow);
   if(candidates.length===1)return candidates[0];
   if(candidates.length>1)return null;
  }return null;
 };
 // Limit reconciliation to visible conversation messages, not account history.
 const selectors=provider==='ChatGPT'?{user:'[data-message-author-role="user"],[data-testid="user-message"],[data-markdown-text-style="user-message"]',reply:'[data-message-author-role="assistant"],[data-markdown-text-style="assistant-message"]'}:
 provider==='DeepSeek'?{user:'[data-role="user"],[data-message-role="user"],.ds-message .ds-collapsible-text',reply:'[data-role="assistant"],[data-message-role="assistant"],.ds-message .ds-markdown'}:
 {user:'[data-testid="user-message"]',reply:'[data-is-streaming],.font-claude-response'};
 const messages=()=>[...document.querySelectorAll(selectors.user)].filter(e=>visible(e)&&!e.closest('textarea,[contenteditable=true],[data-twos-native-card]')).slice(-8);
 const turnHeadings=()=>provider==='ChatGPT'?[...document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role=heading]')].filter(e=>/^(You said|你说|ChatGPT said|ChatGPT 说)[:：]?$/i.test(e.textContent.trim())&&!e.closest('[data-twos-native-card],textarea,[contenteditable=true]')):[];
 const semanticReceipt=()=>{
  const headings=turnHeadings();
  for(let i=0;i<headings.length;i++){
   if(!/^(You said|你说)[:：]?$/i.test(headings[i].textContent.trim()))continue;
   const range=document.createRange();range.setStartAfter(headings[i]);
   if(headings[i+1])range.setEndBefore(headings[i+1]);else range.setEnd(document.body,document.body.childNodes.length);
   // Match the entire chosen body + unique marker. Heading boundaries exclude
   // another answer, composer and our own saved receipt. No history request.
   if(plain(range.cloneContents()).replace(/\s/g,'')===prompt.replace(/\s/g,''))return headings[i];
  }return null;
 };
 const receipt=()=>messages().find(e=>(normalize(e.textContent)===normalize(prompt)||normalize(e.innerText)===normalize(prompt)))||semanticReceipt();
 const busy=()=>[...document.querySelectorAll('button,[role=button]')].some(e=>visible(e)&&/^(stop(?: generating| response)?|停止(?:生成|回复)?)$/i.test(e.getAttribute('aria-label')||e.getAttribute('title')||e.textContent.trim()));
 const result=()=>{
  const user=receipt();if(!user)return null;
  const nextUser=[...messages(),...turnHeadings().filter(e=>/^(You said|你说)[:：]?$/i.test(e.textContent.trim()))].filter(e=>e!==user&&Boolean(user.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING)).sort((a,b)=>a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING?-1:1)[0];
  const replies=[...document.querySelectorAll(selectors.reply)].filter(e=>visible(e)&&!e.closest('[data-twos-native-card]')&&Boolean(user.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING)&&(!nextUser||Boolean(e.compareDocumentPosition(nextUser)&Node.DOCUMENT_POSITION_FOLLOWING)));
  const last=replies.at(-1);
  // DeepSeek's stop icon is not consistently labelled. A reply node can exist
  // while streaming, so require the observed idle composer arrow before calling
  // it a finished reply. Never infer completion from text silence alone.
  const deepSeekShape=provider==='DeepSeek'&&(location.hostname==='chat.deepseek.com'||document.querySelector('.ds-message'));
  const claudeStreaming=provider==='Claude'&&last&&(last.matches('[data-is-streaming="true"]')||last.querySelector('[data-is-streaming="true"]'));
  const settled=last&&!busy()&&!claudeStreaming&&(!deepSeekShape||Boolean(deepSeekSend(false)));
  let reply='';if(settled){
   const controls=[...last.querySelectorAll('button,[role=button],[data-twos-native-card]')].map(e=>[e,e.getAttribute('style')]);
   try{controls.forEach(([e,s])=>e.setAttribute('style',(s||'')+';display:none!important'));reply=last.innerText||'';}
   finally{controls.forEach(([e,s])=>s===null?e.removeAttribute('style'):e.setAttribute('style',s));}
  }
  return {state:settled?'reply':'sent',conversationURL:clean(location.href),...(reply?{reply:reply.slice(0,200000)}:{})};
 };
 const existing=result();if(existing)return existing;
 if(request.inspectOnly)return {state:'unknown'};
 // An old draft may have been manually submitted outside TWOS. Losing that
 // draft is not proof of non-delivery: reconcile rather than recreate/resend.
 if(request.resumeDraft&&!value().trim())return {state:'unknown'};
 if(busy())return {state:'busy'};
 if(value().trim()&&!(request.resumeDraft&&normalize(value())===normalize(prompt)))return {state:'draft_conflict'};
 if(request.preflightOnly)return {state:'ready'};
 if(!same()||clean(location.href)!==original)return {state:'target_changed'};
 input.focus();
 if(input instanceof HTMLTextAreaElement){Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,prompt);input.dispatchEvent(new Event('input',{bubbles:true}));}
 else {
  const range=document.createRange();range.selectNodeContents(input);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
  if(!document.execCommand('insertHTML',false,prompt.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>')))return {state:'unsupported'};
 }
 if(normalize(value())!==normalize(prompt))return {state:'draft'};
 // Optional draft-only mode never reports SENT. Normal transfers require one
 // exact visible send control and then the complete marked user-message echo.
 if(request.draftOnly)return {state:'draft'};
 for(let n=0;n<20;n++){
  await new Promise(r=>setTimeout(r,100));
  if(!same()||clean(location.href)!==original||normalize(value())!==normalize(prompt))return {state:'target_changed'};
  const buttons=[...document.querySelectorAll('button,[role=button]')].filter(e=>visible(e)&&!e.disabled&&e.getAttribute('aria-disabled')!=='true'&&(
   e.matches('[data-testid="send-button"],#composer-submit-button')||/^(Send(?: message| prompt)?|发送(?:消息|提示)?)$/i.test(e.getAttribute('aria-label')||e.getAttribute('title')||e.textContent.trim())));
  const deepSeekControl=deepSeekSend();if(!buttons.length&&deepSeekControl)buttons.push(deepSeekControl);
  if(buttons.length!==1)continue;
  buttons[0].click(); // Exactly one real website control; never guess Enter or another icon.
  for(let j=0;j<40;j++){
   await new Promise(r=>setTimeout(r,125));
   if(!same())return {state:'unknown'};
   const confirmed=result();if(confirmed)return confirmed;
  }
  return {state:'unknown'};
 }
 return {state:'draft'};
})();
