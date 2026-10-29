// Public rendered UI only, in TWOS's isolated content world. Observation never
// returns conversation text. Explicit handoff alone may read one final answer.
(() => {
 'use strict';
 const hosts={'chatgpt.com':'ChatGPT','claude.ai':'Claude','chat.deepseek.com':'DeepSeek'};
 const provider=hosts[location.hostname];
 const visible=e=>Boolean(e?.getClientRects().length)&&getComputedStyle(e).visibility!=='hidden';
 const all=s=>[...document.querySelectorAll(s)].filter(e=>visible(e)&&!e.closest('[data-twos-native-card]'));
 const selectedProvider=()=>provider||(location.hostname==='127.0.0.1'?document.documentElement.dataset.twosFixtureProvider:null);
 const replies=()=>{
  const p=selectedProvider(),s=p==='ChatGPT'?'[data-message-author-role="assistant"],[data-markdown-text-style="assistant-message"]':p==='Claude'?'[data-is-streaming],.font-claude-response':p==='DeepSeek'?'[data-role="assistant"],[data-message-role="assistant"],.ds-message .ds-markdown':null;
  if(!s)return [];
  return all(s).filter(e=>!e.parentElement?.closest(s));
 };
 const input=()=>{
  const fields=all('textarea,#prompt-textarea,[contenteditable=true][role=textbox],.tiptap[contenteditable=true]').filter(e=>!e.disabled&&!e.readOnly&&!e.closest('[data-message-author-role],[data-is-streaming],.font-claude-response,.ds-message'));
  return fields.length===1?fields[0]:null;
 };
 const stop=()=>all('button,[role=button]').some(e=>e.matches('[data-testid="stop-button"]')||/^(stop(?: generating| response)?|停止(?:生成|回复)?)$/i.test(e.getAttribute('aria-label')||e.getAttribute('title')||e.textContent.trim()));
 const deepIdle=()=>{
  let el=input()?.parentElement;
  for(let i=0;el&&i<5;i++,el=el.parentElement){
   if([...el.querySelectorAll('[role=button].ds-button--primary.ds-button--circle svg path')].some(p=>p.getAttribute('d')?.startsWith('M8.3125 0.980206')))return true;
  }return false;
 };
 function observe(){
  if(!selectedProvider())return {state:'unknown',reason:'UNSUPPORTED_PROVIDER'};
  if(document.querySelector('iframe[src*="challenges.cloudflare.com"],#challenge-running,#challenge-stage')||all('h1,h2').some(e=>/security verification|verify you are human|正在进行安全验证|验证您是真人/i.test(e.textContent)))return {state:'waiting_user',reason:'VERIFICATION'};
  if(!input())return {state:all('button,a').some(e=>/^(log in|sign in|登录|登入)$/i.test(e.textContent.trim()))?'waiting_user':'unknown',reason:'INPUT_UNAVAILABLE'};
  const last=replies().at(-1),stream=stop()||Boolean(last&&(last.matches('[data-is-streaming="true"]')||last.querySelector('[data-is-streaming="true"]')));
  if(stream)return {state:'running',reason:'VISIBLE_GENERATION_CONTROL'};
  if(selectedProvider()==='DeepSeek'&&!deepIdle())return {state:'unknown',reason:'GENERATION_STATE_UNCONFIRMED'};
  return {state:'idle',reason:'VISIBLE_IDLE_COMPOSER'};
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
  const controls=[...el.querySelectorAll('button,[role=button],[role=toolbar],time,[data-twos-native-card]'),
   ...[...el.querySelectorAll('h3,[role=heading]')].filter(e=>/^(Claude (?:已回复|说|said|replied)[:：])/.test(e.textContent.trim()))
  ].map(e=>[e,e.getAttribute('style')]);
  try{controls.forEach(([e,s])=>e.setAttribute('style',(s||'')+';display:none!important'));return el.innerText||'';}
  finally{controls.forEach(([e,s])=>s===null?e.removeAttribute('style'):e.setAttribute('style',s));}
 }
 function latest(){
  const status=observe();if(status.state!=='idle')return status;
  const reply=replies().at(-1);if(!reply)return {state:'unknown',reason:'NO_COMPLETE_REPLY'};
  const body=text(reply);if(!body.trim())return {state:'unknown',reason:'EMPTY_REPLY'};
  if(new TextEncoder().encode(body).length>200000)return {state:'unsupported',reason:'REPLY_TOO_LARGE'};
  // No sidebars, unrelated selection, quoted prior card or partial stream.
  return {state:'reply',text:body,message:reply.closest('[data-message-id]')?.getAttribute('data-message-id')||reply.closest('[data-testid^="conversation-turn-"]')?.getAttribute('data-testid')||'latest-rendered-reply'};
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
 function selectedOrLatest(){
  const selection=getSelection();
  if(selection?.rangeCount===1&&!selection.isCollapsed){
   const range=selection.getRangeAt(0),node=range.commonAncestorContainer;
   const element=node.nodeType===Node.ELEMENT_NODE?node:node.parentElement;
   const body=selection.toString();
   const safe=element&&!element.closest('nav,aside,[role=dialog],[role=menu],[data-twos-native-card],textarea,[contenteditable=true]');
   const inReply=replies().some(e=>e.contains(range.startContainer)&&e.contains(range.endContainer));
   if(safe&&body.trim()&&new TextEncoder().encode(body).length<=200000&&(!selectedProvider()||(inReply&&observe().state==='idle'))){
    return {state:'reply',text:body,message:'selected-content'};
   }
   return {state:'unknown',reason:'SELECT_A_COMPLETE_REPLY_NOT_A_FLOATING_CONTROL'};
  }
  return latest();
 }
 window.twosProviderDOM={observe,latest,selectedOrLatest,replies,text,navigationSafety};
})();
