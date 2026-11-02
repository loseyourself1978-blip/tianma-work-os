// Named WKContentWorld only. The host owns route/session/receipts; web content
// cannot grant automatic sending or execution rights. One action area per pane.
(() => {
 'use strict';
 const native=window.webkit?.messageHandlers?.twosHandoff;if(!native)return;
 const post=value=>native.postMessage({...value,source:location.href});
 let zh=__TWOS_ZH__,target={provider:'Codex',binding:''};
 const label=(en,cn)=>zh?cn:en,put=(el,text)=>{if(el.textContent!==text)el.textContent=text;},flag=(el,key,value)=>{if(el[key]!==value)el[key]=value;};
 let auto={enabled:false,supported:false,pending:false,state:'off',reason:''};
 let scheduled=false,returnAvailable=false,active=null,serial=0;
 const records=new Map();
 const api=()=>window.twosProviderDOM;
 const visible=el=>el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden';
 const composer=()=>api()?.composerSelection().element||null;
 const generating=()=>api()?.observe().state==='running';
 const replies=()=>api()?.replies()||[];
 const turnHeadings=()=>api()?.headings()||[];
 const speaker=heading=>api()?.speaker(heading);
 const messageSelector='[data-message-author-role="assistant"],[data-markdown-text-style="assistant-message"]';
 const excludedReceipt='textarea,[contenteditable="true"],[data-twos-native-card]';
 const instructionText=reply=>api()?.text(reply)||'';
 const targetLabel=()=>target.provider==='Codex'?label('Send to Codex','交付 Codex 执行'):label('Send to ','发送到 ')+target.provider;
 // Route revision prevents stale dispatch; persisted destination identity prevents
 // an already delivered reply from regaining Send after refresh or App restart.
 const recordedTarget=record=>!record.binding||record.binding===target.binding||record.binding.split('|').slice(1).join('|')===target.binding.split('|').slice(1).join('|');
 const sourceMatches=record=>{try{const a=new URL(record.source),b=new URL(location.href);a.search=b.search='';a.hash=b.hash='';return a.href===b.href;}catch{return false;}};
 const digest=async text=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))].map(x=>x.toString(16).padStart(2,'0')).join('');
 const reasonText=r=>({
  AMBIGUOUS_COMPOSER:label('Message input is ambiguous. Sending is paused.','输入区域不明确，发送已暂停。'),
  INPUT_UNAVAILABLE:label('Message input is not available yet.','输入区域尚不可用。'),
  REPLY_INTERRUPTED:label('Reply interrupted; it will not be sent as complete.','回复已中断，不会作为完整回复发送。'),
  LATEST_USER_AWAITS_REPLY:label('Waiting for the current reply.','等待当前回复。'),
  REPLY_IDENTITY_PENDING:label('Identifying this reply…','正在核对回复身份…'),
  OBSERVER_UNAVAILABLE:label('Reply status unavailable.','回复状态暂不可用。')
 }[r]||label('Reply status needs verification: ','回复状态待核验：')+r);
 function makeArea(){
  const box=document.createElement('section');box.setAttribute('data-twos-native-card','');
  box.style.cssText='margin:12px 0;font:13px -apple-system,sans-serif;overflow-wrap:anywhere;color:inherit;';
  const row=document.createElement('div');row.style.cssText='display:flex;align-items:center;gap:10px;flex-wrap:wrap;';
  const button=document.createElement('button');button.type='button';button.dataset.twosPrimary='';
  button.style.cssText='padding:8px 12px;border-radius:8px;border:1px solid #8887;background:transparent;color:inherit;cursor:pointer;';
  const toggleLabel=document.createElement('label');toggleLabel.style.cssText='display:inline-flex;align-items:center;gap:5px;cursor:pointer;';
  const toggle=document.createElement('input');toggle.type='checkbox';toggle.dataset.twosAutomatic='';
  // Provider CSS resets native inputs. Keep this scoped control visibly native
  // without changing any of the website's own inputs or global styles.
  toggle.style.cssText='appearance:auto!important;-webkit-appearance:checkbox!important;display:inline-block!important;position:static!important;width:16px!important;height:16px!important;margin:0!important;opacity:1!important;visibility:visible!important;clip:auto!important;clip-path:none!important;flex:0 0 16px;accent-color:#257763;';
  const toggleText=document.createElement('span');toggleLabel.append(toggle,toggleText);
  const status=document.createElement('div');status.setAttribute('role','status');status.style.cssText='margin-top:6px;white-space:pre-wrap;';
  const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent=label('Details','详情');
  const preview=document.createElement('pre');preview.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto;';
  const check=document.createElement('button');check.type='button';check.hidden=true;
  const retry=document.createElement('button');retry.type='button';retry.hidden=true;
  const result=document.createElement('div');result.style.cssText='white-space:pre-wrap;';
  details.append(summary,preview,check,retry,result);row.append(button,toggleLabel);box.append(row,status,details);
  const card={box,button,toggle,toggleText,toggleLabel,status,details,summary,preview,check,retry,result,reply:null,message:'',record:null,pending:false,version:++serial};
  button.addEventListener('click',event=>{
   if(!event.isTrusted)return;
   if(auto.enabled){post({action:'stopAutomaticReplies'});return;}
   const current=api()?.latest();
   if(card!==active||card.pending||!card.reply?.isConnected||current?.state!=='reply'||current.message!==card.message||(card.record&&recordedTarget(card.record)))return;
   const text=instructionText(card.reply);if(text!==current.text||!text.trim())return;
   card.pending=true;render(card);post({action:'handoff',text,message:card.message,targetBinding:target.binding});
  });
  toggle.addEventListener('change',event=>{
   if(!event.isTrusted){toggle.checked=auto.enabled;return;}
   post({action:'automaticReplies',enabled:toggle.checked,targetBinding:target.binding});
   // Reflect the host acknowledgement, never a page-local success boolean.
   toggle.checked=auto.enabled;
  });
  check.addEventListener('click',event=>{
   if(!event.isTrusted||!card.record)return;
   put(status,label('Checking delivery… Nothing is resent.','正在核验投递，不会重新发送。'));check.disabled=true;
   post({action:'inspectHandoff',id:card.record.id});
  });
  retry.addEventListener('click',event=>{if(event.isTrusted&&card.record?.retryable)post({action:'retryHandoff',id:card.record.id});});
  details.addEventListener('toggle',()=>{if(details.open)renderDetails(card);});
  return card;
 }
 function renderDetails(card){
  put(card.preview,card.reply?instructionText(card.reply):'');
  const r=card.record;
  flag(card.check,'hidden',!r||r.provider==='Codex');put(card.check,label('Check delivery','核验投递'));
  flag(card.check,'disabled',r?.inspection==='checking');
  flag(card.retry,'hidden',!r?.retryable);put(card.retry,label('Retry this handoff','重试此交接'));
  put(card.result,r?[r.provider,r.state,r.businessResult,r.inspection,r.error,r.result].filter(Boolean).join('\n'):'');
 }
 function render(card){
  const current=api()?.latest(),complete=current?.state==='reply'&&current.message===card.message&&card.reply?.isConnected;
  const blocked=Boolean((card.record&&recordedTarget(card.record))||card.pending);
  flag(card.button,'hidden',!auto.enabled&&(!complete||blocked));
  flag(card.button,'disabled',false);
  put(card.button,auto.enabled?label('Stop auto-send','停止自动发送'):targetLabel());
  flag(card.toggle,'checked',auto.enabled);flag(card.toggle,'disabled',auto.pending||(!auto.supported&&!auto.enabled));
  put(card.toggleText,label('Automatically send replies to ','自动发送回复到 ')+target.provider);
  if(card.toggle.getAttribute('aria-label')!==card.toggleText.textContent)card.toggle.setAttribute('aria-label',card.toggleText.textContent);
  card.toggle.title=auto.supported?'':label('Auto-send shares website replies only. Codex execution retains separate permissions.','自动发送仅交流网页回复。Codex 执行保留独立权限。');
  put(card.summary,label('Details','详情'));
  let note='';
  if(auto.enabled)note=auto.reason||label('Auto-send on · ','自动发送中 · ')+(auto.count||0);
  else if(auto.state==='paused')note=label('Auto-send paused · ','自动发送已暂停 · ')+(auto.reason||'');
  else if(card.record){
   const r=card.record;note=card.legacyIdentity?label('Matching older receipt found; message identity needs verification. Nothing is resent.','找到内容相同的旧回执，消息身份需核验，不会重复发送。'):['sent','reply','accepted'].includes(r.state)?label('Sent to ','已发送到 ')+(r.provider||'Codex'):
    ['sending','preparing','queued'].includes(r.state)?label('Sending…','发送中…'):label('See details · ','详情：')+(r.state||'unknown');
  }else if(card.pending)note=label('Sending…','发送中…');
  else if(current?.state==='unknown'&&!['NO_COMPLETE_REPLY','EMPTY_REPLY','LATEST_USER_AWAITS_REPLY'].includes(current.reason))note=reasonText(current.reason);
  put(card.status,note);flag(card.status,'hidden',!note);
  flag(card.details,'hidden',!card.record&&!complete);
  if(card.details.open)renderDetails(card);
 }
 async function attachReceipt(card,record){
  const legacy=/^rendered-assistant-\d+$/.test(record.message)||record.message==='latest-rendered-reply';
  if(!sourceMatches(record)||!card.reply||record.message!==card.message&&!legacy)return;
  const version=card.version,text=instructionText(card.reply);
  if(await digest(text)!==record.hash)return;
  if(active!==card||version!==card.version||!card.reply.isConnected||instructionText(card.reply)!==text)return;
  if(card.record&&card.record.id!==record.id&&(card.record.createdAt||0)>(record.createdAt||0))return;
  card.record=record;card.legacyIdentity=legacy&&record.message!==card.message;card.pending=false;render(card);
 }
 function inspect(){
  scheduled=false;const phase=api()?.observe();
  if(phase?.state==='waiting_user'){if(active)flag(active.box,'hidden',true);return;}
  const list=replies(),reply=list.at(-1)||null,input=composer();
  const available=phase?.state==='idle'&&input&&!(input instanceof HTMLTextAreaElement?input.value:input.innerText).trim();
  const becameAvailable=available&&!returnAvailable;returnAvailable=Boolean(available);
  let added=false;
  const message=reply?api().identity(reply):'';
  if(!active||active.reply!==reply||active.message!==message||!active.box.isConnected){
   // A provider remount may retain a copied DOM card without its callbacks.
   // Keep exactly one host-owned action area; never retain that stale hit target.
   document.querySelectorAll('[data-twos-native-card]').forEach(e=>e.remove());
   active=makeArea();active.reply=reply;active.message=message;added=true;
   if(reply)reply.insertAdjacentElement('afterend',active.box);
   else if(input)input.closest('form')?.insertAdjacentElement('beforebegin',active.box)||input.insertAdjacentElement('beforebegin',active.box);
   else document.body.append(active.box);
   for(const r of records.values())attachReceipt(active,r);
  }
  flag(active.box,'hidden',false);render(active);
  if(added||becameAvailable)post({action:'ready'});
 }
 window.twosHandoffUpdate=async record=>{if(!sourceMatches(record))return;records.set(record.id,record);inspect();if(active)await attachReceipt(active,record);};
 window.twosHandoffNotice=text=>{if(active&&!active.record){active.pending=false;render(active);put(active.status,text);flag(active.status,'hidden',!text);}};
 window.twosHandoffTarget=value=>{if(!value||typeof value.provider!=='string'||typeof value.binding!=='string')return;target=value;inspect();};
 window.twosHandoffAutoState=value=>{if(!value||typeof value.enabled!=='boolean')return;auto=value;inspect();};
 window.twosHandoffLanguage=value=>{zh=Boolean(value);inspect();};
 window.twosDeliverResult=async ({id,text,source,inspectOnly})=>{
  const same=()=>{const url=new URL(location.href);url.search='';url.hash='';return url.href===source;};
  const marker='[TWOS delivery '+id+']';
  const seen=()=>{
   if([...document.querySelectorAll('[data-message-author-role="user"], [data-markdown-text-style="user-message"], [data-testid="user-message"]')].some(el=>visible(el)&&(el.innerText||'').includes(marker)))return true;
   // The current official site also exposes plain user turns with an accessible
   // “You said / 你说” heading instead of the older message-role attribute.
   // Never count our composer or result card as proof of website delivery.
   const headings=turnHeadings();
   for(let i=0;i<headings.length;i++){
    const heading=headings[i];if(speaker(heading)!=='user')continue;
    // A shared layout wrapper may contain both speakers, so climbing parents
    // cannot establish a message boundary. Use the semantic speaker headings.
    const range=document.createRange();range.setStartAfter(heading);
    if(headings[i+1])range.setEndBefore(headings[i+1]);
    else range.setEnd(document.body,document.body.childNodes.length);
    const fragment=range.cloneContents();
    fragment.querySelectorAll(excludedReceipt+','+messageSelector).forEach(el=>el.remove());
    if((fragment.textContent||'').includes(marker))return true;
   }
   return false;
  };
  if(!same())return 'pending';if(seen())return 'confirmed';if(inspectOnly)return 'unknown';
  if(generating())return 'pending';
  const el=composer();
  if(!el)return 'pending';const value=()=>el instanceof HTMLTextAreaElement?el.value:el.innerText;
  if(value().trim())return 'pending';
  const prompt=marker+'\n'+text;
  el.focus();
  if(el instanceof HTMLTextAreaElement){Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(el,prompt);el.dispatchEvent(new Event('input',{bubbles:true}));}
  else{
   const range=document.createRange();range.selectNodeContents(el);const selection=getSelection();selection.removeAllRanges();selection.addRange(range);
   // WebKit's insertText applies macOS smart substitutions (--- becomes —),
   // including inside Markdown tables and code. Insert fully escaped text with
   // explicit line breaks; never interpret any model-provided HTML.
   const escaped=prompt.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');
   if(!document.execCommand('insertHTML',false,escaped))return 'pending';
  }
  for(let n=0;n<25;n++){
   await new Promise(resolve=>setTimeout(resolve,100));
   if(!same()||value().replace(/\r/g,'')!==prompt)return 'pending';
   const send=document.querySelector('[data-testid="send-button"],#composer-submit-button,button[aria-label="Send prompt"],button[aria-label="发送提示"],button[aria-label="发送"],button[aria-label="Send"]');
   if(!send||send.disabled)continue;
   send.click();
   for(let j=0;j<40;j++){await new Promise(resolve=>setTimeout(resolve,125));if(same()&&seen())return 'confirmed';}
   return 'unknown';
  }
  // The draft remains visible and intact if the official send action was not
  // available. Never press Enter or guess a different website control.
  return 'pending';
 };
 const schedule=()=>{if(!scheduled){scheduled=true;setTimeout(inspect,350);}};
 window.twosHandoffIdentityReady=schedule;
 const observer=new MutationObserver(schedule);observer.observe(document.documentElement,{childList:true,subtree:true,attributes:true,attributeFilter:['hidden','aria-hidden','disabled','data-is-streaming','contenteditable']});
 document.addEventListener('input',schedule,true);inspect();post({action:'ready'});
})();
