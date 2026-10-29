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
 const plain=el=>{const copy=el.cloneNode(true);copy.querySelectorAll('button,[role=button],[data-twos-native-card],textarea,[contenteditable=true]').forEach(x=>x.remove());copy.querySelectorAll('h1,h2,h3,h4,h5,h6,[role=heading]').forEach(x=>{if(/^(You said|你说)[:：]?$/i.test(x.textContent.trim()))x.remove();});return copy.textContent||'';};
 // Inspect challenge/login before any DOM mutation. Do not touch the challenge frame.
 const heading=[...document.querySelectorAll('h1,h2')].filter(visible).map(x=>x.textContent).join(' ');
 if(document.querySelector('iframe[src*="challenges.cloudflare.com"],#challenge-running,#challenge-stage')||/security verification|verify you are human|正在进行安全验证|验证您是真人/i.test(heading))return {state:'verification'};
 const alerts=[...document.querySelectorAll('[role=alert],[data-testid*=toast]')].filter(e=>visible(e)&&!e.closest('[data-message-author-role],[data-is-streaming],.font-claude-response,.ds-message,[data-twos-native-card]')).map(e=>e.innerText||'').join(' ');
 if(/at capacity|overloaded|服务繁忙|容量不足/i.test(alerts))return {state:'provider_limited',reason:'SERVICE_CAPACITY'};
 if(/usage limit|rate limit|limit reached|too many requests|额度|达到.{0,6}上限/i.test(alerts))return {state:'provider_limited',reason:'SERVICE_LIMIT'};
 if(/network error|connection lost|网络错误|网络连接失败/i.test(alerts))return {state:'unknown',reason:'NETWORK_UNAVAILABLE'};
 const composerFields=()=>[...document.querySelectorAll('textarea,#prompt-textarea,[contenteditable=true][role=textbox],.tiptap[contenteditable=true]')].filter(e=>visible(e)&&!e.disabled&&!e.readOnly&&!e.closest('[data-twos-native-card],[data-message-author-role],.ds-markdown'));
 const fields=composerFields();
 if(fields.length!==1){
  const login=[...document.querySelectorAll('button,a')].filter(visible).some(e=>/^(log in|sign in|登录|登入)$/i.test(e.textContent.trim()));
  return {state:login?'login':'not_loaded'};
 }
 if(request.readinessOnly)return {state:'input_ready'};
 let input=fields[0];const value=()=>input instanceof HTMLTextAreaElement?input.value:input.innerText;
 const prompt='[TWOS handoff '+request.id+']\n'+request.text;
 // Read-only control metadata for an unavailable upload path. Never include
 // values, filenames, page text, URLs, credentials or arbitrary DOM dumps.
 const uploadShape=()=>[...document.querySelectorAll('input[type=file]')].slice(0,12).map((e,index)=>{
  const chain=[];for(let p=e.parentElement,n=0;p&&p!==document.body&&n<4;p=p.parentElement,n++)chain.push({tag:p.tagName,role:p.getAttribute('role'),testID:p.getAttribute('data-testid'),className:String(p.className||'').slice(0,180),visible:visible(p),containsDraft:p.contains(input)});
  return {index,accept:e.accept.slice(0,400),multiple:e.multiple,disabled:e.disabled,directory:e.webkitdirectory||e.hasAttribute('directory'),capture:e.getAttribute('capture'),ariaHidden:Boolean(e.closest('[aria-hidden=true]')),chain};
 });
 const isSendControl=e=>e.matches('[data-testid="send-button"],#composer-submit-button,[data-testid="chat-input-send"]')||/^(Send(?: message| prompt)?|发送(?:消息|提示)?)$/i.test(e.getAttribute('aria-label')||e.getAttribute('title')||e.textContent.trim());
 const sendShape=()=>[...document.querySelectorAll('button,[role=button]')].filter(isSendControl).slice(0,8).map(e=>({tag:e.tagName,testID:e.getAttribute('data-testid'),visible:visible(e),disabled:Boolean(e.disabled),ariaDisabled:e.getAttribute('aria-disabled'),inHistory:Boolean(e.closest('[data-twos-native-card],[data-message-author-role],[data-is-streaming],.font-claude-response'))}));
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
 const selectors=provider==='ChatGPT'?{user:'[data-message-author-role="user"],[data-testid="user-message"],[data-markdown-text-style="user-message"],[data-user-message-bubble]',reply:'[data-message-author-role="assistant"],[data-markdown-text-style="assistant-message"]'}:
 provider==='DeepSeek'?{user:'[data-role="user"],[data-message-role="user"],.ds-message .ds-collapsible-text',reply:'[data-role="assistant"],[data-message-role="assistant"],.ds-message .ds-markdown'}:
 {user:'[data-testid="user-message"]',reply:'[data-is-streaming],.font-claude-response'};
 const messages=()=>[...document.querySelectorAll(selectors.user)].filter(e=>visible(e)&&!e.closest('textarea,[contenteditable=true],[data-twos-native-card]')).slice(-8);
 const matchesPrompt=e=>{
  const body=plain(e),compact=v=>v.replace(/\s/g,'');
  if(compact(body)===compact(prompt))return true;
  if(provider==='Claude'||provider==='ChatGPT'){
   // Both observed user-message renderers use inline Markdown code rather
   // than echoing its backticks. Restore only delimiters proved by the frozen
   // submitted body, inside actual inline CODE nodes. Never strip punctuation
   // globally or accept a prefix; changed code/body still fails reconciliation.
   const copy=e.cloneNode(true);
   for(const code of copy.querySelectorAll('code')){
    if(code.closest('pre'))continue;
    const value=code.textContent;
    for(let n=1;n<=16;n++){
     const fence='`'.repeat(n),wrapped=fence+value+fence;let at=prompt.indexOf(wrapped);
     while(at>=0){
      if(prompt[at-1]!=='`'&&prompt[at+wrapped.length]!=='`'){code.replaceWith(document.createTextNode(wrapped));at=-2;break;}
      at=prompt.indexOf(wrapped,at+1);
     }
     if(at===-2)break;
    }
   }
   if(compact(plain(copy))===compact(prompt))return true;
  }
  if(provider!=='ChatGPT'||!request.files?.length)return false;
  // The visible ChatGPT user-message wrapper prepends attachment captions.
  // Require the unique marker and the ENTIRE exact submitted body through
  // the end of this user message, never a substring inside an assistant reply.
  const at=body.indexOf('[TWOS handoff '+request.id+']');
  return at>=0&&compact(body.slice(at))===compact(prompt);
 };
 const turnHeadings=()=>provider==='ChatGPT'?[...document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role=heading]')].filter(e=>/^(You said|你说|ChatGPT said|ChatGPT 说)[:：]?$/i.test(e.textContent.trim())&&!e.closest('[data-twos-native-card],textarea,[contenteditable=true]')):[];
 const semanticReceipt=()=>{
  const headings=turnHeadings();
  for(let i=0;i<headings.length;i++){
   if(!/^(You said|你说)[:：]?$/i.test(headings[i].textContent.trim()))continue;
   // A modern ChatGPT turn has a semantic user heading but no stable user
   // data attribute. Its sibling tool/thinking output precedes the assistant
   // heading. Match a bounded single-user container before considering the
   // wider heading range; never accept only a prefix of the submitted body.
   let container=headings[i].parentElement;
   for(let depth=0;container&&container!==document.body&&depth<6;depth++,container=container.parentElement){
    if(headings.filter(h=>container.contains(h)).length!==1||container.querySelector(selectors.reply))break;
    if(matchesPrompt(container))return container;
   }
   const range=document.createRange();range.setStartAfter(headings[i]);
   if(headings[i+1])range.setEndBefore(headings[i+1]);else range.setEnd(document.body,document.body.childNodes.length);
   // Match the entire chosen body + unique marker. Heading boundaries exclude
   // another answer, composer and our own saved receipt. No history request.
   if(matchesPrompt(range.cloneContents()))return headings[i];
  }return null;
 };
 // Current ChatGPT renders a semantic user bubble with a nested searchable
 // body. Its collapse decoration is outside that body. Require the entire
 // submitted text inside the same user bubble, never any arbitrary text node
 // or an assistant quotation containing the marker.
 const matchesUser=e=>matchesPrompt(e)||(provider==='ChatGPT'&&e.matches('[data-user-message-bubble]')&&[...e.querySelectorAll('[data-search-result-target]')].some(body=>body.closest('[data-user-message-bubble]')===e&&matchesPrompt(body)));
 const receipt=()=>messages().find(e=>(normalize(e.textContent)===normalize(prompt)||normalize(e.innerText)===normalize(prompt)||matchesUser(e)))||semanticReceipt();
 const busy=()=>[...document.querySelectorAll('button,[role=button]')].some(e=>visible(e)&&/^(stop(?: generating| response)?|停止(?:生成|回复)?)$/i.test(e.getAttribute('aria-label')||e.getAttribute('title')||e.textContent.trim()));
 const result=()=>{
  const user=receipt();if(!user)return null;
  const nextUser=[...messages(),...turnHeadings().filter(e=>/^(You said|你说)[:：]?$/i.test(e.textContent.trim()))].filter(e=>e!==user&&!user.contains(e)&&!e.contains(user)&&Boolean(user.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING)).sort((a,b)=>a.compareDocumentPosition(b)&Node.DOCUMENT_POSITION_FOLLOWING?-1:1)[0];
  const replies=[...document.querySelectorAll(selectors.reply)].filter(e=>visible(e)&&!e.closest('[data-twos-native-card]')&&Boolean(user.compareDocumentPosition(e)&Node.DOCUMENT_POSITION_FOLLOWING)&&(!nextUser||Boolean(e.compareDocumentPosition(nextUser)&Node.DOCUMENT_POSITION_FOLLOWING)));
  const last=replies.at(-1);
  // DeepSeek's stop icon is not consistently labelled. A reply node can exist
  // while streaming, so require the observed idle composer arrow before calling
  // it a finished reply. Never infer completion from text silence alone.
  const deepSeekShape=provider==='DeepSeek'&&(location.hostname==='chat.deepseek.com'||document.querySelector('.ds-message'));
  const claudeStreaming=provider==='Claude'&&last&&(last.matches('[data-is-streaming="true"]')||last.querySelector('[data-is-streaming="true"]'));
  const settled=last&&!busy()&&!claudeStreaming&&(!deepSeekShape||Boolean(deepSeekSend(false)));
  let reply='';if(settled){
   const fileReference=e=>e.closest('p,td,li')&&/^(?:打开 .+ 的预览|Open .+ preview)$/i.test(e.getAttribute('aria-label')||'');
   const controls=[...last.querySelectorAll('button,[role=button],[role=toolbar],time,[data-twos-native-card]')].filter(e=>!fileReference(e)).map(e=>[e,e.getAttribute('style')]);
   try{controls.forEach(([e,s])=>e.setAttribute('style',(s||'')+';display:none!important'));reply=window.twosProviderDOM?.text?window.twosProviderDOM.text(last):(last.innerText||'');}
   finally{controls.forEach(([e,s])=>s===null?e.removeAttribute('style'):e.setAttribute('style',s));}
  }
  if(new TextEncoder().encode(reply).length>200000)return {state:'unknown',reason:'REPLY_TOO_LARGE'};
  return {state:settled&&reply.trim()?'reply':'sent',conversationURL:clean(location.href),attachments:request.files?.map(({id,name,mime,size,hash})=>({id,name,mime,size,hash}))||[],...(reply?{reply,replyMessage:last.closest('[data-message-id]')?.getAttribute('data-message-id')||last.closest('[data-testid^=conversation-turn-]')?.getAttribute('data-testid')||'rendered-answer'}:{})};
 };
 const existing=result();if(existing)return existing;
 if(request.inspectOnly)return {state:'unknown',reason:'EXACT_RECEIPT_NOT_FOUND · SEND_CONTROL_SHAPE '+JSON.stringify(sendShape())+(request.files?.length?' · UPLOAD_CONTROL_SHAPE '+JSON.stringify(uploadShape()):'')};
 // An old draft may have been manually submitted outside TWOS. Losing that
 // draft is not proof of non-delivery: reconcile rather than recreate/resend.
 if(request.resumeDraft&&!value().trim())return {state:'unknown'};
 if(busy())return {state:'busy'};
 if(value().trim()&&!(request.resumeDraft&&normalize(value())===normalize(prompt)))return {state:'draft_conflict'};
 // Some providers put uploaded cards beside, not inside, their labelled
 // composer. Expand only through bounded draft ancestors which contain no
 // conversation messages; never count an earlier message's file card.
 const composerScopes=[];
 const refreshComposerScopes=()=>{
  composerScopes.length=0;
  for(let root=input.parentElement,depth=0;root&&depth<8&&root!==document.body;root=root.parentElement,depth++){
   if(root.querySelector(selectors.user+','+selectors.reply))break;
   composerScopes.push(root);
  }
 };
 refreshComposerScopes();
 const bindExactComposer=()=>{
  const current=composerFields();
  if(current.length!==1||normalize(current[0] instanceof HTMLTextAreaElement?current[0].value:current[0].innerText)!==normalize(prompt))return false;
  input=current[0];refreshComposerScopes();return true;
 };
 const inComposer=e=>visible(e)&&composerScopes.some(root=>root.contains(e))&&!e.closest('nav,aside,[data-twos-native-card],[data-message-author-role],[data-message-role],[data-role="user"],[data-role="assistant"],[data-testid="user-message"],[data-is-streaming],.font-claude-response,.ds-message');
 // Past uploaded files belong to conversation history, not the current draft.
 // Do not mistake them for newly selected attachments or re-upload evidence.
 const removeLabel=/^(?:Remove(?: attachment| file)?|移除(?:附件)?)\s*/i;
 const fileLabel=e=>[e.getAttribute('aria-label'),e.getAttribute('title')].find(v=>v&&!removeLabel.test(v)&&/\.[a-z0-9]{1,10}$/i.test(v.trim()))?.trim();
 const attachmentChips=()=>{
  // ChatGPT images are filename-labelled popup buttons. Text/PDF cards
  // additionally have a sibling Remove button. Count each real card once;
  // discover unknown existing cards too, not just names in this request.
  const primary=[...document.querySelectorAll('[data-testid*=attachment],[data-testid*=file-upload],[data-testid*=file-card],button,[role=button]')]
   .filter(e=>inComposer(e)&&(e.matches('[data-testid*=attachment],[data-testid*=file-upload],[data-testid*=file-card]')||fileLabel(e)));
  const outer=primary.filter(e=>!primary.some(other=>other!==e&&other.contains(e)));
  const removals=[...document.querySelectorAll('[aria-label^="Remove attachment"],[aria-label^="Remove file"],[aria-label^="移除附件"],button[aria-label^="移除 "],button[aria-label^="Remove "]')].filter(inComposer);
  return [...outer,...removals.filter(e=>!outer.some(card=>card.contains(e)||(e.parentElement?.contains(card)&&fileLabel(card)&&(e.getAttribute('aria-label')||'').replace(removeLabel,'').trim()===fileLabel(card))))];
 };
 if(!request.files?.length&&attachmentChips().length)return {state:'draft_conflict',reason:'EXISTING_WEBSITE_ATTACHMENTS_PRESERVED'};
 if(request.preflightOnly)return {state:'ready'};
 if(!same()||clean(location.href)!==original)return {state:'target_changed'};
 // Keep the exact marked body as a recoverable draft while uploads settle.
 input.focus();
 if(input instanceof HTMLTextAreaElement){Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,prompt);input.dispatchEvent(new Event('input',{bubbles:true}));}
 else {
  const range=document.createRange();range.selectNodeContents(input);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
  if(!document.execCommand('insertHTML',false,prompt.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>')))return {state:'unsupported'};
 }
 // Rich-text editors may reconcile their controlled value asynchronously.
 // Wait for the exact frozen body, never normalize away a content difference.
 const draftDeadline=performance.now()+2000;let stableDraft=0;
 while(performance.now()<draftDeadline){
  if(!same()||clean(location.href)!==original)return {state:'target_changed'};
  stableDraft=bindExactComposer()?stableDraft+1:0;
  if(stableDraft>=2)break;
  await new Promise(r=>setTimeout(r,50));
 }
 if(stableDraft<2)return {state:'draft',reason:'EXACT_DRAFT_NOT_CONFIRMED_NO_MESSAGE_SENT'};
 if(!same()||clean(location.href)!==original)return {state:"target_changed"};
 // Exact native-selected bytes only. File objects use the website's standard
 // file-input/change path, never a private upload endpoint or filename proxy.
 if(request.files?.length){
  const files=request.files;
  if(files.length>8||files.reduce((n,f)=>n+f.size,0)>12000000)return {state:'unsupported',reason:'ATTACHMENT_LIMIT'};
  const manifest=JSON.stringify(files.map(({id,name,mime,size,hash})=>({id,name,mime,size,hash})));
  window.twosUploadReceipts ||= new Map();
  const previous=window.twosUploadReceipts.get(request.id);
  if(previous&&previous!==manifest)return {state:'unknown',reason:'ATTACHMENT_SCOPE_CHANGED'};
  const chips=attachmentChips;
  if(!previous){
   if(chips().length)return {state:'draft_conflict',reason:'EXISTING_WEBSITE_ATTACHMENTS_PRESERVED'};
   const uploadInputs=()=>{
    const candidates=[...document.querySelectorAll('input[type=file]')].filter(e=>!e.disabled&&!e.closest('[inert],[aria-hidden=true]')&&!e.webkitdirectory&&!e.hasAttribute('directory')&&(files.length===1||e.multiple)&&files.every(f=>{
    const accept=e.accept.toLowerCase().split(',').map(x=>x.trim()).filter(Boolean);
    return !accept.length||accept.includes('*/*')||accept.some(a=>a===f.mime||a==='.'+f.name.split('.').at(-1).toLowerCase()||(a.endsWith('/*')&&f.mime.startsWith(a.slice(0,-1))));
    }));
    // Hidden file inputs can belong to a different composer or modal. Prefer
    // one within this exact draft's bounded subtree; never pick the first of
    // several equally eligible controls.
    for(const root of composerScopes){
     const scoped=candidates.filter(e=>root.contains(e));
     if(scoped.length)return scoped; // nearest actual draft subtree wins
    }
    return candidates;
   };
   let inputs=uploadInputs();
   const controlDeadline=performance.now()+2500;let openedMenu=false;
   while(inputs.length!==1&&performance.now()<controlDeadline){
    if(!same()||clean(location.href)!==original)return {state:'target_changed'};
    // ChatGPT's supported Add files menu may mount its native file input
    // lazily on a new chat. Open only the verified local composer menu, never
    // the file-picker action, history, a connector or a private upload API.
    if(inputs.length===0&&provider==='ChatGPT'&&!openedMenu){
     const menus=[...document.querySelectorAll('button')].filter(e=>inComposer(e)&&/^(Add files and more|添加文件等内容)$/i.test(e.getAttribute('aria-label')||''));
     if(menus.length===1&&menus[0].getAttribute('aria-expanded')!=='true'){menus[0].click();openedMenu=true;}
    }
    await new Promise(r=>setTimeout(r,100));
    if(!bindExactComposer())return {state:'draft',reason:'EXACT_DRAFT_NOT_CONFIRMED_NO_MESSAGE_SENT'};
    inputs=uploadInputs();
   }
   if(inputs.length!==1)return {state:'unsupported',reason:'EXACT_FILE_UPLOAD_CONTROL_UNAVAILABLE · eligible='+inputs.length+' · total='+document.querySelectorAll('input[type=file]').length+' · UPLOAD_CONTROL_SHAPE '+JSON.stringify(uploadShape())};
   const transfer=new DataTransfer();
   for(const f of files){
    const bytes=Uint8Array.from(atob(f.base64),c=>c.charCodeAt(0));
    const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
    if(bytes.length!==f.size||hash!==f.hash)return {state:'unsupported',reason:'ATTACHMENT_BYTES_CHANGED'};
    transfer.items.add(new File([bytes],f.name,{type:f.mime}));
   }
   if(!same()||clean(location.href)!==original)return {state:'target_changed'};
   if(!bindExactComposer()||!inputs[0].isConnected||uploadInputs().length!==1||uploadInputs()[0]!==inputs[0])return {state:'draft',reason:'UPLOAD_CONTROL_CHANGED_NO_MESSAGE_SENT'};
   inputs[0].files=transfer.files;inputs[0].dispatchEvent(new Event('change',{bubbles:true}));
   window.twosUploadReceipts.set(request.id,manifest);
  }
  let uploaded=false;
  for(let n=0;n<80;n++){
   if(!same()||clean(location.href)!==original)return {state:'unknown',reason:'ATTACHMENT_TARGET_CHANGED'};
   if(!bindExactComposer()){await new Promise(r=>setTimeout(r,100));continue;}
   const nodes=chips().filter(e=>!chips().some(other=>other!==e&&other.contains(e)));
   const available=new Set(nodes),remaining=[];
   const labels=e=>[fileLabel(e),...(e.innerText||'').split('\n'),(e.getAttribute('aria-label')||'').replace(removeLabel,''),e.getAttribute('title')||''].filter(Boolean).map(v=>v.trim());
   // The observed ChatGPT UI adds '(1)' before the extension when a name
   // already exists in this conversation. Original File bytes/name/hash stay
   // bound to the native manifest. Match exact names first, then only this
   // provider's visible duplicate-name suffix; never accept arbitrary aliases.
   for(const f of files){const chip=[...available].find(e=>labels(e).includes(f.name));if(chip)available.delete(chip);else remaining.push(f);}
   const names=remaining.every(f=>{
    if(provider!=='ChatGPT')return false;
    const dot=f.name.lastIndexOf('.');if(dot<=0)return false;
    const stem=f.name.slice(0,dot),ext=f.name.slice(dot);
    const chip=[...available].find(e=>labels(e).some(v=>v.startsWith(stem)&&v.endsWith(ext)&&/^\([1-9][0-9]*\)$/.test(v.slice(stem.length,-ext.length))));
    if(!chip)return false;available.delete(chip);return true;
   });
   const progress=[...document.querySelectorAll('[role=progressbar],[data-testid*=uploading]')].some(inComposer);
   if(names&&nodes.length===files.length&&!progress){uploaded=true;break;}
   await new Promise(r=>setTimeout(r,250));
  }
  if(!uploaded){
   // Bounded control-shape diagnostics only: no DOM/text dump or account data.
   // Each ordinal refers to a caller-selected file, never an unselected file.
   const controls=[...document.querySelectorAll('button,[role=button]')];
   const shape=files.map((f,i)=>({file:i,controls:controls.filter(e=>[(e.innerText||''),e.getAttribute('aria-label')||'',e.getAttribute('title')||''].some(v=>v.includes(f.name))).map(e=>({tag:e.tagName,role:e.getAttribute('role'),visible:visible(e),inComposer:inComposer(e),selectedByChip:chips().includes(e),aria:Boolean(e.getAttribute('aria-label')),title:Boolean(e.getAttribute('title'))})).slice(0,4)}));
   return {state:'draft',reason:'UPLOAD_NOT_CONFIRMED_NO_MESSAGE_SENT',diagnostics:{scopeCount:composerScopes.length,chipCount:chips().length,shape}};
  }
 }
 // Optional draft-only mode never reports SENT. Normal transfers require one
 // exact visible send control and then the complete marked user-message echo.
 if(request.draftOnly)return {state:'draft'};
 const sendDeadline=performance.now()+8000;
 while(performance.now()<sendDeadline){
  await new Promise(r=>setTimeout(r,100));
  if(!same()||clean(location.href)!==original)return {state:'target_changed'};
  if(!bindExactComposer())return {state:'draft',reason:'EXACT_DRAFT_CHANGED_NO_MESSAGE_SENT'};
  const candidates=[...document.querySelectorAll('button,[role=button]')].filter(e=>visible(e)&&!e.disabled&&e.getAttribute('aria-disabled')!=='true'&&!e.closest('[inert],[aria-hidden=true],[data-twos-native-card],[data-message-author-role],[data-is-streaming],.font-claude-response')&&isSendControl(e));
  const scoped=composerScopes.map(root=>candidates.filter(e=>root.contains(e))).find(items=>items.length);
  const buttons=scoped||candidates;
  const deepSeekControl=deepSeekSend();if(!buttons.length&&deepSeekControl)buttons.push(deepSeekControl);
  if(buttons.length!==1)continue;
  buttons[0].click(); // Exactly one real website control; never guess Enter or another icon.
  // WebKit can throttle timers in a background pane. Bound elapsed time as
  // well as poll count; forty delayed callbacks must not turn a five-second
  // receipt check into forty seconds. An unresolved send stays unknown.
  const receiptDeadline=performance.now()+5000;
  for(let j=0;j<40;j++){
   await new Promise(r=>setTimeout(r,125));
   if(!same())return {state:'unknown'};
   const confirmed=result();if(confirmed)return confirmed;
   if(performance.now()>=receiptDeadline)break;
  }
  return {state:'unknown'};
 }
 return {state:'draft',reason:'EXACT_SEND_CONTROL_NOT_READY_NO_MESSAGE_SENT · SEND_CONTROL_SHAPE '+JSON.stringify(sendShape())};
})();
