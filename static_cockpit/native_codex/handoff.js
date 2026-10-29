// Runs in a named WKContentWorld. Remote page scripts cannot call its native
// handler. An explicit click sends this selected instruction to its bound web
// target. Codex retains its separate execution permissions and directory gates.
(() => {
 'use strict';
 const native=window.webkit?.messageHandlers?.twosHandoff;
 if(!native)return;
 const post=value=>native.postMessage({...value,source:location.href});
 const cards=new Map(), messages=new WeakMap();let scheduled=false,returnAvailable=false;
 let target={provider:"Codex",binding:""};
 let zh=__TWOS_ZH__;const label=(en,cn)=>zh?cn:en;
 const targetLabel=(provider=target.provider)=>provider==='Codex'?label('Send to Codex','交付 Codex 执行'):label('Send to ','发送到 ')+provider;
 const receiptProvider=record=>record?.provider||'Codex';
 const sourceKey=el=>el.closest('[data-message-id]')?.getAttribute('data-message-id')||el.closest('[data-testid^="conversation-turn-"]')?.getAttribute('data-testid')||'';
 const visible=el=>el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden';
 function instructionText(reply){
  if(window.twosProviderDOM?.text)return window.twosProviderDOM.text(reply);
  // Official replies can contain follow-up suggestions and code-copy controls.
  // Read rendered text with those controls temporarily excluded, preserving
  // paragraphs/code whitespace and restoring the site's exact inline styles.
  const controls=[...reply.querySelectorAll('button,[role="button"],[data-twos-native-card]')].map(el=>[el,el.getAttribute('style')]);
  try{for(const [el,style] of controls)el.setAttribute('style',(style||'')+';display:none!important;');return reply.innerText||'';}
  finally{for(const [el,style] of controls)style===null?el.removeAttribute('style'):el.setAttribute('style',style);}
 }
 const messageSelector='[data-message-author-role="assistant"],[data-markdown-text-style="assistant-message"]';
 const excludedReceipt='textarea,[contenteditable="true"],[data-twos-native-card]';
 const speaker=heading=>/^(?:You said|你说)[:：]?$/i.test(heading.textContent.trim())?'user':/^(?:ChatGPT said|ChatGPT 说)[:：]?$/i.test(heading.textContent.trim())?'assistant':null;
 const turnHeadings=()=>[...document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"]')].filter(el=>speaker(el)&&!el.closest(messageSelector+','+excludedReceipt));
 function composer(){
  // Writing/canvas replies are editable too. They are conversation content,
  // never a draft or a destination for execution results. Hidden legacy
  // fields must not win over the current visible message composer either.
  const fields=[...document.querySelectorAll('#prompt-textarea,textarea,[contenteditable=true][role=textbox]')].filter(el=>
   visible(el)&&!el.disabled&&!el.readOnly&&!el.closest(messageSelector+',[data-twos-native-card]'));
  const prompt=fields.find(el=>el.id==='prompt-textarea');
  if(prompt)return prompt;
  const formFields=fields.filter(el=>el.closest('form'));
  return formFields.length===1?formFields[0]:fields.length===1?fields[0]:null;
 }
 function generating(){
  const status=window.twosProviderDOM?.observe();
  if(status&&status.reason!=='UNSUPPORTED_PROVIDER'&&status.state!=='idle')return true;
  // The current official site labels the composer stop button simply “停止”.
  // Its public summaries also use assistant-message markup while streaming.
  return [...document.querySelectorAll('button')].some(el=>visible(el)&&(
   el.matches('[data-testid="stop-button"]')||
   /^(?:Stop(?: generating| response)?|停止(?:生成|回复)?)$/i.test(el.getAttribute('aria-label')||el.getAttribute('title')||el.textContent.trim())));
 }
 function replies(){
  if(location.hostname==='claude.ai'||location.hostname==='chat.deepseek.com')return window.twosProviderDOM?.replies()||[];
  const groups=new Map(),headings=turnHeadings();
  for(const el of document.querySelectorAll('[data-message-author-role="assistant"], [data-markdown-text-style="assistant-message"]')){
   if(el.parentElement?.closest('[data-message-author-role="assistant"], [data-markdown-text-style="assistant-message"]')||!visible(el))continue;
   // A turn may contain several public summary blocks followed by one answer.
   // Keep its last answer only. Unkeyed site variants expose only the latest
   // complete answer rather than treating every summary as a separate task.
   const preceding=headings.filter(heading=>Boolean(heading.compareDocumentPosition(el)&Node.DOCUMENT_POSITION_FOLLOWING)).at(-1);
   const group=el.closest('article,[data-testid^="conversation-turn-"]')||sourceKey(el)||preceding||'latest';
   groups.set(group,el);
  }
  return [...groups.values()];
 }
 function inspect(){
  scheduled=false;
  // Login/challenge pages stay untouched; no card injection or automatic send.
  const phase=window.twosProviderDOM?.observe();
  if(phase&&phase.state==='waiting_user')return;
  // Never send incomplete streaming content just because a DOM node appeared.
  const busy=generating(),candidates=busy?[]:replies();
  const input=composer();
  const available=!busy&&input&&!(input instanceof HTMLTextAreaElement?input.value:input.innerText).trim();
  const becameAvailable=available&&!returnAvailable;returnAvailable=Boolean(available);
  let added=false;
  for(const [reply,card] of cards){
   if(!reply.isConnected||(!card.record&&!candidates.includes(reply))){card.box.remove();cards.delete(reply);messages.delete(reply);}
   else card.button.disabled=generating()||Boolean(card.record&&!card.record.retryable&&!(receiptProvider(card.record)==='Codex'&&['cancelled','rejected'].includes(card.record.state)));
  }
  for(const reply of candidates){
   if(messages.has(reply))continue;
   const box=document.createElement('section');box.setAttribute('data-twos-native-card','');box.style.cssText='margin:16px 0;padding:12px;border:1px solid #8885;border-radius:12px;font:14px -apple-system,sans-serif;overflow-wrap:anywhere;';
   const button=document.createElement('button');button.type='button';button.textContent=targetLabel();button.style.cssText='padding:9px 14px;border-radius:8px;border:1px solid #8887;cursor:pointer;background:transparent;color:inherit;';
   const status=document.createElement('p');status.style.cssText='margin:8px 0 0;white-space:pre-wrap;';
   const details=document.createElement('details');details.dataset.twosResult='';details.hidden=true;const summary=document.createElement('summary');summary.textContent=label('Codex result','Codex 执行结果');const result=document.createElement('div');result.style.cssText='white-space:pre-wrap;line-height:1.6;margin-top:10px;';details.append(summary,result);
   const discuss=document.createElement('button');discuss.type='button';discuss.hidden=true;discuss.textContent=label('Continue discussing this result','继续讨论此结果');discuss.style.cssText=button.style.cssText;
   const sendReply=document.createElement('button');sendReply.type='button';sendReply.hidden=true;sendReply.style.cssText=button.style.cssText;sendReply.textContent=label('Send reply to the other pane','将回复发送到另一侧');
   const check=document.createElement('button');check.type='button';check.hidden=true;check.textContent=label('Check delivery','核验送达');check.style.cssText=button.style.cssText;
   const preview=document.createElement('details');preview.dataset.twosSendPreview='';const previewLabel=document.createElement('summary');previewLabel.textContent=label('View selected content','查看本次发送内容');const previewText=document.createElement('div');previewText.style.cssText='white-space:pre-wrap;overflow-wrap:anywhere;max-height:240px;overflow:auto;';preview.append(previewLabel,previewText);
   const card={reply,box,button,status,details,result,discuss,check,sendReply,preview,message:sourceKey(reply),record:null};added=true;messages.set(reply,card);cards.set(reply,card);
   preview.addEventListener('toggle',()=>{if(preview.open)previewText.textContent=instructionText(reply);});
   button.addEventListener('click',event=>{if(!event.isTrusted||generating()||!reply.isConnected)return;if(card.record?.retryable){post({action:'retryHandoff',id:card.record.id});return;}if(card.record&&receiptProvider(card.record)!=='Codex')return;const text=instructionText(reply);if(!text.trim())return;post({action:'handoff',text,message:card.message,targetBinding:target.binding});});
   discuss.addEventListener('click',event=>{if(event.isTrusted&&card.record)post({action:'discuss',id:card.record.id});});
   check.addEventListener('click',event=>{if(event.isTrusted&&card.record){status.textContent=label('Checking delivery… Nothing is resent.','正在检查投递… 不会重新发送。');check.disabled=true;post({action:'inspectHandoff',id:card.record.id});}});
   sendReply.addEventListener('click',event=>{if(event.isTrusted&&card.record)post({action:'sendReply',id:card.record.id});});
   box.append(button,check,status,preview,details,sendReply,discuss);reply.insertAdjacentElement('afterend',box);
  }
  if(added||becameAvailable)post({action:'ready'});
 }
 window.twosHandoffUpdate=async record=>{
  inspect();
  for(const card of cards.values()){
   if(!card.reply.isConnected)continue;
   if(record.message&&card.message!==record.message){
    // Some sites expose no durable DOM message ID. A toolbar handoff's
    // latest-answer fallback may bind only this latest card, still checked
    // below against the exact persisted body hash and native conversation.
    if(record.message!=='latest-rendered-reply'||card.reply!==replies().at(-1))continue;
   }
   const digest=async text=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text)))].map(x=>x.toString(16).padStart(2,'0')).join('');
   const hash=await digest(instructionText(card.reply));
   // Historical receipts are immutable, including older extraction formats.
   if(hash!==record.hash&&await digest(card.reply.innerText||'')!==record.hash)continue;
   if(card.record&&card.record.id!==record.id&&(card.record.createdAt||0)>(record.createdAt||0))continue;
   card.record=record;
   const provider=receiptProvider(record);card.details.querySelector('summary').textContent=provider+label(' result',' 结果');
   const states={provider_limited:label('Provider limit or capacity · paused','网站限制或容量不足 · 已暂停'),queued:label('Queued for the original conversation','已在原会话排队'),queue_paused:label('Queue paused · resume from Handoff history','队列已暂停 · 请从交接记录继续'),busy:label('Target is replying · handoff saved','目标正在回复 · 交接已保存'),not_loaded:label('Target input is not available','目标输入尚不可用'),draft_conflict:label('Existing website draft preserved · not sent','网站已有草稿，已保留 · 未发送'),preparing:label('Verifying target','正在核对目标'),sending:label('Sending','发送中'),accepted:provider+label(' accepted',' 已接收'),sent:label('Sent to ','已发送到 ')+provider,draft:label('Draft only · send in the website','仅填入草稿 · 请在网站发送'),verification:label('Human verification required','需要真人验证'),login:label('Sign in required','需要登录'),target_changed:label('Destination changed · not sent','目标已变化 · 未发送'),unsupported:label('Website sending is not supported','不支持网站自动发送'),reply:label('Reply received · no local file created','已收到代码/回复 · 未创建本机文件'),running:label('Running','执行中'),completed:label('Execution channel finished','执行通道已结束'),failed:label('Failed','失败'),interrupted:label('Stopped','已停止'),cancelled:label('Queue cancelled','已从队列删除'),unknown:label('Delivery needs verification','送达状态待核验'),rejected:label('Not delivered','未送达')};
   const business={blocked:label('Task BLOCKED · inspect the reason below','任务受阻 BLOCKED · 原因见下方'),failed:label('Task failed','任务失败'),partial:label('Task partly completed','任务部分完成'),reported_pass:label('Executor reports PASS · artifact acceptance not verified','执行器回报 PASS · 产物尚待验收'),unverified:label('Business result not verified','业务结果尚未核验')};
   card.status.textContent=[business[record.businessResult],states[record.state]||record.state,record.cwd,record.model,record.effort,provider==='Codex'?record.error:null,record.inspection==='checking'?label('Checking delivery… Nothing is resent.','正在检查投递… 不会重新发送。'):record.inspection?label('Last check: ','最近检查：')+record.inspection:null].filter(Boolean).join('\n');
   card.check.disabled=record.inspection==='checking';card.sendReply.hidden=provider==='Codex'||record.state!=='reply'||!record.result;
   card.details.hidden=!record.result;card.result.textContent=record.result||'';card.discuss.hidden=!record.result||provider!=='Codex';card.check.hidden=provider==='Codex';card.check.textContent=label('Check delivery','核验送达');if(record.retryable)card.details.open=true;
   card.button.disabled=!record.retryable&&!(provider==='Codex'&&['cancelled','rejected'].includes(record.state));card.button.textContent=record.retryable?targetLabel(provider)+(provider==='Codex'?label(' · new attempt',' · 新一次复验'):label(' · confirm destination',' · 核对目标')):(provider==='Codex'?label('Sent to Codex','已交付 Codex'):provider+label(' handoff',' 交接'));
   if(record.state==='draft')card.button.textContent=label('Continue draft to ','继续发送草稿到 ')+provider;
  }
 };

 window.twosHandoffTarget=value=>{
  if(!value||typeof value.provider!=='string'||typeof value.binding!=='string')return;
  target=value;for(const card of cards.values())if(!card.record)card.button.textContent=targetLabel();
 };
 window.twosHandoffLanguage=value=>{
  zh=Boolean(value);
  for(const card of cards.values()){
   if(!card.record)card.button.textContent=targetLabel();
   card.preview.querySelector('summary').textContent=label('View selected content','查看本次发送内容');card.sendReply.textContent=label('Send reply to the other pane','将回复发送到另一侧');
   card.details.querySelector('summary').textContent=label('Codex result','Codex 执行结果');card.discuss.textContent=label('Continue discussing this result','继续讨论此结果');
   if(card.record)window.twosHandoffUpdate(card.record);
  }
 };
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
 const observer=new MutationObserver(schedule);observer.observe(document.documentElement,{childList:true,subtree:true});
 document.addEventListener('input',schedule,true);inspect();post({action:'ready'});
})();
