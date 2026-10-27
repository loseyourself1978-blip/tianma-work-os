'use strict';
(() => {
 const $=id=>document.getElementById(id), E=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let D={},lang='en',state=null,projects=[],project=null,chat=null,tools=null,tab='',mobile='center',hidden=[],left=240,right=360;
 let workbenchScroll=0;
 let draft='',selected=[],search={source_ids:[],search:''},generation=0,sending=false,composing=false,dirty=false,saveTimer,saveQueue=Promise.resolve(),createPromise=null,sendKey=null;
 let authStep='welcome',authEmail='',purpose='signup',challenge=null,mailConfigured=false,polling=false,modalFocus=null,importPreview=null,targetPreview=null,projectRequest=crypto.randomUUID();
 const markdown=window.twosMarkdown;
 const t=k=>D[k]?.[lang==='zh'?1:0]||k;
 const b=(key,action,extra='')=>`<button type="button" data-action="${E(action)}" ${extra}>${E(t(key))}</button>`;
 const input=(key,id,value='',type='text')=>`<label for="${id}">${E(t(key))}<input id="${id}" type="${type}" value="${E(value)}" ${type==='password'?'autocomplete="current-password"':''}></label>`;
 const check=(key,id,value=false)=>`<label><input type="checkbox" id="${id}" ${value?'checked':''}> ${E(t(key))}</label>`;
 const localize=(root=document)=>root.querySelectorAll('[data-i18n]').forEach(n=>n.textContent=t(n.dataset.i18n));
 function alertError(error){const code=error.code||error.message||'ERROR';$('alerts').title=code;$('alerts').textContent=D['error.'+code]?t('error.'+code):t(({MODEL_NOT_CONNECTED:'notConnected',PROVIDER_AUTH_REQUIRED:'authRequired',EMAIL_SERVICE_UNAVAILABLE:'emailBlocked',EMAIL_CODE_INVALID:'invalidCode',AUTH_RATE_LIMIT:'rateCode',PASSWORD_TOO_SHORT:'passwordShort',PASSWORD_MISMATCH:'passwordMismatch',AUTH_INVALID:'loginInvalid',EMAIL_SEND_FAILED:'sendFailed',DRAFT_VERSION_CHANGED:'draftConflict',PDF_TEXT_REQUIRED:'pdfTextRequired',DEVELOPMENT_PROJECT_REQUIRED:'developmentRequired',CHAT_BUSY:'chatBusy',CHAT_DELETED:'chatDeleted'})[code]||'error');$('alerts').hidden=false;}
 function clearAlert(){$('alerts').hidden=true;}
 async function api(url,body){const r=await fetch(url,{credentials:'same-origin',cache:'no-store',...(body!==undefined?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});let data;try{data=await r.json();}catch{throw new Error('NETWORK_RESPONSE');}if(!r.ok){if(r.status===401&&state){state=null;generation++;authStep='login';renderAuth();}throw Object.assign(new Error(data.error?.code||'REQUEST_FAILED'),{code:data.error?.details?.code||data.error?.code||data.detail?.code||'HTTP_'+r.status});}return data;}
 const route=suffix=>`/api/r2/wb/chats/${chat.id}${suffix}`;
 function dialog(title,content,footer=''){modalFocus=document.activeElement;$('dialog').innerHTML=`${b('close','close','class="dialog-close"')}<h2 id="dialog-title">${E(t(title))}</h2>${content}<div class="toolbar">${footer}</div>`;if(!$('dialog').open)$('dialog').showModal();}
 function close(){if($('dialog').open)$('dialog').close();modalFocus?.focus?.();}
 function passwordField(id,key='password'){let autocomplete='current-password';if(id==='new-password')autocomplete='new-password';return `<label for="${id}">${E(t(key))}</label><div class="password-field"><input id="${id}" type="password" minlength="12" maxlength="200" autocomplete="${autocomplete}" required>${b('showPassword','show',`data-input="${id}" class="show-password"`)}</div>`;}
 function renderAuth(){
  $('auth-screen').hidden=!!state;$('workspace').hidden=!state;$('account').hidden=!state;$('mobile-tabs').hidden=!state;$('pane-controls').hidden=!state;
  if(state)return;
  let content='',title='authWelcome',subtitle='welcomeHint';
  if(authStep==='welcome')content=b('register','signup','class="primary auth-main"')+b('login','login','class="auth-alt"')+b('legacyLogin','legacy','class="auth-link"');
  if(['signup','login','reset'].includes(authStep)){title=authStep==='signup'?'signupTitle':authStep==='login'?'loginTitle':'resetTitle';subtitle=authStep==='signup'?'signupEmailNote':authStep==='reset'?'resetNote':'loginNote';content=input('email','auth-email',authEmail,'email')+`<button class="primary auth-main" type="submit">${E(t(authStep==='reset'?'sendReset':'continue'))}</button>`+b('legacyLogin','legacy','class="auth-link"');}
  if(['signup-password','login-password'].includes(authStep)){title=authStep==='signup-password'?'passwordTitle':'loginPasswordTitle';subtitle='identityBoundary';content=`<div class="auth-email-pill">${E(authEmail)}${b('changeEmail',authStep.startsWith('signup')?'signup':'login','class="auth-link"')}</div>`+passwordField('auth-password')+`<p class="helper">${E(t('passwordRule'))}</p><button class="primary auth-main" type="submit">${E(t(authStep.startsWith('signup')?'sendCode':'login'))}</button>`+b('forgot','reset','class="auth-link"');}
  if(authStep==='verify'){title='verifyTitle';subtitle='proofPending';content=`<p>${E(authEmail)}</p><label for="auth-code">${E(t('code'))}</label><input id="auth-code" class="otp-input" inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" maxlength="6" required><p class="helper">${E(t('codeExpiry'))}</p><button class="primary auth-main" type="submit">${E(t('verifyEmail'))}</button><div class="toolbar">${b('resend','resend','class="auth-link"')}${b('changeEmail',purpose==='reset'?'reset':'signup','class="auth-link"')}</div>`;}
  if(authStep==='reset-password'){title='resetPasswordTitle';subtitle='passwordRule';content=passwordField('new-password','newPassword')+passwordField('confirm-password','confirmPassword')+`<button class="primary auth-main" type="submit">${E(t('savePassword'))}</button>`;}
  if(authStep==='legacy'){title='legacyLogin';subtitle='loginNote';content=input('username','local-username')+passwordField('auth-password')+`<button class="primary auth-main" type="submit">${E(t('login'))}</button><p class="auth-footer"><a href="/project-manager">${E(t('localAuth'))}</a></p>`;}
  $('auth-screen').innerHTML=`<div class="auth-layout"><section class="auth-story"><div class="eyebrow">TIANMA WORK OS</div><h1>${E(t('authIntro'))}</h1><p>${E(t('authStory'))}</p></section><div class="auth-card">${authStep!=='welcome'?b('backAuth','auth-back','class="back"'):''}<h2>${E(t(title))}</h2><p class="auth-subtitle">${E(t(subtitle))}</p><form id="auth-form">${content}</form>${!mailConfigured?`<p class="notice">${E(t('emailBlocked'))}</p>`:''}<p class="auth-footer">${E(t('identityBoundary'))}</p></div></div>`;
 }
 async function submitAuth(){
  if(['signup','login','reset'].includes(authStep)){authEmail=$('auth-email').value.trim();if(!authEmail.includes('@'))throw new Error('EMAIL_INVALID');if(authStep!=='reset'){authStep+='-password';renderAuth();return;}purpose='reset';const r=await api('/api/auth/email/begin',{email:authEmail,purpose,password:'',confirmation:true});challenge=r.challenge_id;authStep='verify';}
  else if(authStep==='signup-password'){purpose='signup';const r=await api('/api/auth/email/begin',{email:authEmail,purpose,password:$('auth-password').value,confirmation:true});challenge=r.challenge_id;authStep='verify';}
  else if(authStep==='login-password'){await api('/api/auth/email/login',{email:authEmail,password:$('auth-password').value});await initialize();return;}
  else if(authStep==='legacy'){await api('/api/auth/login',{username:$('local-username').value,password:$('auth-password').value});await initialize();return;}
  else if(authStep==='verify'){const r=await api('/api/auth/email/verify',{challenge_id:challenge,purpose,code:$('auth-code').value});if(r.state==='RESET_AUTHORIZED')authStep='reset-password';else {await initialize();return;}}
  else if(authStep==='reset-password'){await api('/api/auth/email/reset',{challenge_id:challenge,password:$('new-password').value,confirmation:$('confirm-password').value});authStep='login';challenge=null;}
  renderAuth();
 }
 async function initialize(){
  const [session,prefs,mail]=await Promise.all([api('/api/auth/session'),api('/api/r2/preferences'),api('/api/auth/email/status')]);lang=prefs.locale==='zh-CN'?'zh':'en';mailConfigured=mail.configured;$('lang').value=lang;
  if(!session.authenticated){state=null;if(mail.pending){authEmail=mail.pending.email;purpose=mail.pending.purpose;challenge=mail.pending.challenge_id;authStep=mail.pending.state==='RESET_AUTHORIZED'?'reset-password':'verify';}renderAuth();return;}
  [state,projects,tools]=await Promise.all([api('/api/r2/wb/state'),api('/api/r2/projects'),api('/api/r2/tools')]);
  const layout=state.layout||{};hidden=layout.hidden||[];left=layout.left||240;right=layout.right||360;tab=layout.tab||'';
  if(layout.chat_id&&state.chats.some(c=>c.id===layout.chat_id)){await selectChat(layout.chat_id,false,layout);}
  else {chat=null;project=null;draft='';selected=[];tab='';render();}
 }
 async function ensureChat(){if(chat)return chat.id;if(createPromise)return createPromise;const pid=project?.id||null;const key=crypto.randomUUID();createPromise=(async()=>{const r=await api('/api/r2/wb/chats',{request_id:key,project_id:pid});chat=await api(`/api/r2/wb/chats/${r.id}`);state.chats.push({id:chat.id,title:'',project_id:pid});createPromise=null;await saveLayout();renderTree();return chat.id;})();try{return await createPromise;}finally{createPromise=null;}}
 function saveDraft(){
  clearTimeout(saveTimer);
  saveQueue=saveQueue.catch(()=>{}).then(async()=>{
   if(!dirty||!state)return;if(!chat&&!draft&&!selected.length&&!search.source_ids.length)return;
   await ensureChat();const cid=chat.id,body=draft,attachments=[...selected],tool=JSON.stringify(search),version=chat.draft_version;
   const r=await api(`/api/r2/wb/chats/${cid}/draft`,{body,attachments,version,...JSON.parse(tool)});
   if(chat?.id===cid){chat.draft_version=r.version;if(draft===body&&JSON.stringify(selected)===JSON.stringify(attachments)&&JSON.stringify(search)===tool)dirty=false;$('save-state').textContent=t('saved');}
  });return saveQueue;
 }
 async function saveLayout(){if(!state)return;if(!tab)workbenchScroll=Math.round($('chat-region').scrollTop);return api('/api/r2/wb/layout',{chat_id:chat?.id||null,left,right,hidden,tab,scroll:workbenchScroll});}
 async function selectChat(cid,save=true,restore={}){
  if(save)await saveDraft();const g=++generation;
  const next=await api(`/api/r2/wb/chats/${cid}`);const nextProject=next.project_id?await api('/api/r2/projects/'+next.project_id):null;
  if(g!==generation)return;chat=next;project=nextProject;draft=chat.draft;selected=chat.draft_attachments;dirty=false;sendKey=null;
  tab=restore.tab||'';search=chat.draft_tool||{source_ids:[],search:''};mobile='center';workbenchScroll=restore.scroll||0;
  render();$('chat-region').scrollTop=workbenchScroll;await saveLayout();
 }
 async function selectProject(pid){await saveDraft();const g=++generation;if(projects.find(p=>p.id===pid)?.legacy){await api(`/api/r2/wb/projects/${pid}/open`,{confirmation:true});await refreshState();}const next=await api('/api/r2/projects/'+pid);if(g!==generation)return;project=next;const existing=state.chats.find(c=>c.project_id===pid);if(existing){await selectChat(existing.id,false);return;}chat=null;draft='';selected=[];search={source_ids:[],search:''};dirty=false;tab='';workbenchScroll=0;mobile='center';render();await saveLayout();}
 async function refreshState(){const next=await api('/api/r2/wb/state');state=next;projects=await api('/api/r2/projects');}
 function renderTree(){
  $('conversation-heading').innerHTML=`<strong>${E(chat?.title||t('newMessage'))}</strong>${chat&&!project?b('saveToProject','save-project'):''}`;
  $('tree').innerHTML=projects.map(p=>`<button class="project-title ${project?.id===p.id?'selected':''}" data-action="project" data-id="${p.id}">${E(p.name)}</button>${project?.id===p.id?`<div class="chat-list">${state.chats.filter(c=>c.project_id===p.id).map(chatButton).join('')}${b('newChat','new-chat',`data-project="${p.id}" class="new-chat-side"`)}</div>`:''}`).join('')+(state.chats.some(c=>!c.project_id)?`<span class="label loose-label">${E(t('recentChats'))}</span>${state.chats.filter(c=>!c.project_id).map(chatButton).join('')}`:'');
 }
 function chatButton(c){return `<div class="chat-row ${chat?.id===c.id?'selected':''}"><button class="chat-item" data-action="chat" data-id="${E(c.id)}">${E(c.title||t('newMessage'))}</button><button class="chat-menu" data-action="chat-menu" data-id="${E(c.id)}" aria-label="${E(t('chatOptions'))}">⋯</button></div>`;}
 function deletedChats(){dialog('deletedChats',`<p>${E(t('deletedNote'))}</p>${(state.deleted_chats||[]).map(c=>`<div class="deleted-row"><span>${E(c.title||t('newMessage'))}</span>${b('restoreChat','restore-chat',`data-id="${E(c.id)}"`)}</div>`).join('')||`<p>${E(t('noDeletedChats'))}</p>`}`);}
 async function deleteChat(cid){
  await saveDraft();await api(`/api/r2/wb/chats/${cid}/delete`,{confirmation:true});
  if(chat?.id===cid){generation++;chat=null;draft='';selected=[];search={source_ids:[],search:''};dirty=false;tab='';sendKey=null;}
  close();await refreshState();render();await saveLayout();
 }

 function renderPanes(){const ws=$('workspace');ws.className='workspace'+(!project?' home-layout':'')+(!project&&!chat?.messages.length?' landing':'')+hidden.map(p=>' hide-'+p).join('');ws.dataset.mobile=mobile;ws.style.setProperty('--left',left+'px');ws.style.setProperty('--right',right+'px');$('pane-controls').innerHTML=['left','center',...(project?['right']:[])].map(p=>b(p==='left'?'projects':p==='center'?'chat':'codex','pane',`data-pane="${p}" aria-pressed="${!hidden.includes(p)}" class="small"`)).join('');$('mobile-tabs').innerHTML=['left','center',...(project?['right']:[])].map(p=>b(p==='left'?'projects':p==='center'?'chat':'codex','mobile',`data-pane="${p}" class="${mobile===p?'active':''}"`)).join('');}
 // Polls keep unchanged nodes and the reader's expanded evidence in place.
 function updateContent(id,html){
  const node=$(id);if(node._renderedMarkup===html)return;
  const follow=id==='right-body'&&node.scrollHeight-node.scrollTop-node.clientHeight<96;
  const expanded=new Map([...node.querySelectorAll('details[data-detail]')].map(n=>[n.dataset.detail,n.open])),scroll=node.scrollTop;
  const fields=[...node.querySelectorAll('textarea,input,select')].map(el=>({id:el.id,question:el.dataset.question,event:el.dataset.event,form:el.form?.dataset.delivery,name:el.name,value:el.value,focused:document.activeElement===el,start:el.selectionStart,end:el.selectionEnd}));
  if(id==='messages'){
   const template=document.createElement('template');template.innerHTML=html;
   const key=n=>n.dataset.message||n.dataset.delivery;
   const existing=new Map([...node.children].filter(n=>key(n)).map(n=>[key(n),n]));let cursor=node.firstElementChild;
   for(const fresh of [...template.content.children]){const old=existing.get(key(fresh)),markup=fresh.outerHTML;const child=old&&old._sourceMarkup===markup?old:fresh;child._sourceMarkup=markup;
    if(child!==cursor)node.insertBefore(child,cursor);else cursor=cursor.nextElementSibling;
    if(child===fresh&&old){if(old===cursor)cursor=cursor.nextElementSibling;old.remove();}existing.delete(key(fresh));
   }
   for(const old of existing.values())old.remove();
  }else node.innerHTML=html;
  node._renderedMarkup=html;
  for(const saved of fields){const el=[...node.querySelectorAll('textarea,input,select')].find(x=>saved.id?x.id===saved.id:saved.question?x.dataset.question===saved.question&&x.dataset.event===saved.event:x.form?.dataset.delivery===saved.form&&x.name===saved.name);if(el){el.value=saved.value;if(saved.focused){el.focus({preventScroll:true});if(el.setSelectionRange)el.setSelectionRange(saved.start,saved.end);}}}
  node.querySelectorAll('details[data-detail]').forEach(n=>{if(expanded.has(n.dataset.detail))n.open=expanded.get(n.dataset.detail);});node.scrollTop=follow?node.scrollHeight:scroll;
 }
 const deliveryUI=window.TWOSDelivery({api,E,markdown,lang:()=>lang,chat:()=>chat,project:()=>project,connection:()=>state?.connection,models:()=>tools.models,
  error:alertError,errorText:code=>D['error.'+code]?t('error.'+code):'',render,dialog:(title,content,footer)=>{dialog(title,content,footer);$('dialog-title').textContent=title;},closeDialog:close,navigate:(next)=>{tab=next;renderDetail();},
  comment:(text)=>{tab='';renderDetail();draft=text;dirty=true;$('draft').value=draft;$('draft').focus();},
  showRight:()=>{hidden=hidden.filter(p=>p!=='right');mobile='right';renderPanes();},
  refresh:async(expected)=>{const cid=expected||chat?.id;if(!cid)return;const next=await api(`/api/r2/wb/chats/${cid}`);if(chat?.id!==cid)return;chat.messages=next.messages;chat.handoffs=next.handoffs;chat.deliveries=next.deliveries;chat.project_id=next.project_id;if(next.project_id)project=await api('/api/r2/projects/'+next.project_id);await refreshState();render();},
 });
 function messageActivity(m,pending){
  const events=m.evidence?.public_activity||[],summaries=events.filter(x=>x.kind==='summary'&&x.text);
  const latest=events.at(-1),code=latest?.kind==='summary'?'PROVIDER_THINKING':latest?.code||(m.state==='QUEUED'?'PROVIDER_QUEUED':'PROVIDER_CONNECTING');
  const progress=pending?`<p class="message-progress" role="status"><span class="progress-pulse" aria-hidden="true"></span>${E(t('progress.'+code))}</p>`:'';
  return progress+(summaries.length?`<details class="message-reasoning" data-detail="reasoning-${E(m.id)}" ${pending?'open':''}><summary>${E(t('reasoningSummary'))}</summary><div class="markdown">${summaries.map(x=>markdown(x.text)+(x.truncated?`<p>${E(t('summaryTruncated'))}</p>`:'')).join('')}</div></details>`:'');
 }
 function messageFailure(m){
  const code=m.evidence?.error_code||'',key='error.'+code;
  return D[key]?t(key):t(m.state==='CANCELLED'?'responseCancelled':m.state==='INTERRUPTED'?'responseInterrupted':'responseFailed');
 }
 function messageDetails(m){
  const e=m.evidence||{},fields=[['diagnosticCode',e.error_code||t('diagnosticUnavailable')],['model',e.requested_model],['tool',m.client],['duration',Number.isFinite(e.duration_seconds)?e.duration_seconds+' '+t('seconds'):null],['diagnosticReference',e.private_evidence?.receipt_id]];
  return `<details class="message-evidence" data-detail="evidence-${E(m.id)}"><summary>${E(t('messageDetails'))}</summary><dl>${fields.filter(x=>x[1]).map(([label,value])=>`<dt>${E(t(label))}</dt><dd>${E(value)}</dd>`).join('')}</dl>${(e.warning_codes||[]).length?`<ul>${[...new Set(e.warning_codes)].filter(c=>D['progress.'+c]).map(c=>`<li>${E(t('progress.'+c))}</li>`).join('')}</ul>`:''}<p>${E(t('noAutomaticReplay'))}</p></details>`;
 }
 function renderMessages(){
  const scroll=$('chat-region'),nearBottom=scroll.scrollHeight-scroll.scrollTop-scroll.clientHeight<100;
  $('welcome').innerHTML=!chat?.messages.length?`<div class="welcome"><h2>${!project?'<span class="slogan-brand">TWOS</span>':''}${E(t(project?'introTitle':'slogan'))}</h2>${project?`<p>${E(t('intro'))}</p>`:''}</div>`:'';
  updateContent('messages',(chat?.messages||[]).map(m=>{
   const pending=['QUEUED','RUNNING'].includes(m.state),failed=['FAILED','INTERRUPTED','CANCELLED'].includes(m.state);
   const body=m.body?(m.role==='user'?E(m.body):markdown(m.body)):'';
   const status=failed?`<p class="message-notice" role="status">${E(messageFailure(m))}</p>`:'';
   const evidence=failed?messageDetails(m):'';
   const repair=failed&&['PROVIDER_MODEL_UNAVAILABLE','MODEL_NOT_ADVERTISED','MODEL_CATALOG_UNAVAILABLE','PROVIDER_AUTH_REQUIRED','EXECUTABLE_MISSING_OR_CHANGED','EXECUTOR_CONFIGURATION_UNSUPPORTED'].includes(m.evidence?.error_code)?b('reviewConnection','repair-connection','class="repair-connection"'):'';
   return `<article data-message="${E(m.id)}" class="message ${E(m.role)}" aria-label="${E(t(m.role==='user'?'you':m.role==='execution'?'codex':'assistant'))}">${m.role==='assistant'?messageActivity(m,pending):''}<div class="body ${m.role==='user'?'':'markdown'}">${body}</div>${status}<div class="message-actions">${repair}${m.body?b('copy','copy-message',`data-id="${E(m.id)}"`):''}${m.role==='assistant'&&m.state==='COMPLETED'&&!chat?.deliveries?.some(d=>d.source_message_id===m.id||['PROPOSED','READY'].includes(d.state))?b('handoff','handoff','class="handoff-btn"'):''}</div>${evidence}</article>`;
  }).join('')+deliveryUI.proposals());
  const running=chat?.messages.some(m=>['QUEUED','RUNNING'].includes(m.state));$('send').disabled=!!running||sending;$('cancel-discussion').hidden=!running;if(nearBottom)scroll.scrollTop=scroll.scrollHeight;
 }
 function renderAttachments(){$('attachments').innerHTML=(chat?.attachments||[]).filter(a=>selected.includes(a.id)).map(a=>`<span class="chip"><a href="${route('/attachments/'+a.id)}" target="_blank" rel="noopener">${a.mime.startsWith('image/')?`<img alt="${E(a.name)}" src="${route('/attachments/'+a.id)}">`:''}${E(a.name)}</a>${b('removeAttachment','remove',`data-id="${a.id}"`)}</span>`).join('');$('send-consent-row').hidden=!selected.length&&!search.source_ids.length;}
 function renderRight(){
  if(chat?.deliveries?.some(d=>d.specification.kind!=='configuration'&&!['SUPERSEDED','REJECTED'].includes(d.state))){updateContent('right-body',deliveryUI.panel());return;}
  let content=`<div class="execution-empty"><h3>${E(t('emptyExecTitle'))}</h3><p>${E(t('emptyExec'))}</p></div>`;
  for(const h of chat?.handoffs||[]){const w=h.work;
   content+=`<section class="exec-card"><p class="quiet-note">${E(t('historicalTask'))}</p><h3>${E(w.title)}</h3><p>${E((w.plan?.allowed_files||[]).join(', '))}</p><div class="toolbar">${w.state==='BUILT'?b('resumeChecks','review',`data-work="${w.id}"`):w.state==='RUNNING'?b('stop','stop',`data-work="${w.id}"`):''}</div></section>`;
   for(const e of h.executions){let output=e.output||'';try{const parsed=JSON.parse(output);output=parsed.summary||parsed.message||'';}catch(_){}
    content+=`<section class="exec-card"><strong>${E(t(e.phase==='reviewer'?'reviewer':e.phase==='executor'?'executor':'planner'))}</strong>${e.error_code?`<p class="notice">${E(e.error_code==='REQUEST_BUDGET_EXHAUSTED'?t('providerQuota'):e.error_code)}</p>`:''}<div class="markdown">${markdown(output)}</div></section>`;
   }
  }
  updateContent('right-body',content);
 }
 function render(){renderAuth();if(!state)return;document.documentElement.lang=lang==='zh'?'zh-CN':'en';$('lang').value=lang;$('language-label').textContent=t('language');localize();renderPanes();renderTree();$('project-name').textContent=project?.name||'';$('nav').innerHTML=project?['overview','sources','team','tasks','deliverables'].map(k=>b(k,'tab',`data-tab="${k}"`)).join(''):'';$('conversation-heading').innerHTML=`<strong>${E(chat?.title||t('newMessage'))}</strong>${chat&&!project?b('saveToProject','save-project'):''}`;$('draft').value=draft;$('draft').placeholder=t(project?'messagePlaceholder':'starter');$('composer-note').textContent=t(!project&&!chat?.messages.length?'homeNote':'composerNote');$('model-state').textContent=state.connection?(project?.integrated?.team?.planner||state.connection.model):t('notConnected');renderMessages();renderAttachments();renderRight();renderDetail();}
 function modelSelect(key,id,value=''){
  const models=[...new Set([...(tools.models||[]),...(value?[value]:[])])];
  models.sort((a,b)=>(a==='gpt-6.1-sol'?-1:b==='gpt-6.1-sol'?1:a.localeCompare(b)));
  const chosen=value||models[0]||'';
  return `<label for="${id}">${E(t(key))}<select class="model-select" id="${id}" required>${models.length?'':`<option value="">${E(t('noModels'))}</option>`}${models.map(m=>`<option value="${E(m)}" ${m===chosen?'selected':''}>${E(m)}</option>`).join('')}</select></label>`;
 }
 function modelInputs(team){return ['planner','executor','reviewer'].map(r=>modelSelect(r,r,team[r]||state.connection?.model||'')).join('');}
 function renderDetail(){const active=!!tab;for(const id of ['chat-region','composer-area','conversation-heading'])$(id).hidden=active;$('detail').hidden=!active;if(!active||!project)return;let content='';
  if(tab==='overview')content=`<p>${E(project.goal||t('overviewDesc'))}</p><p>${E(t('accountNote'))}</p>`;
  if(tab==='sources')content=`<p>${E(t('importBoundary'))}</p>${b('upload','import-sources','class="primary"')}${project.sources.length?project.sources.map(s=>`<div class="source-row">${E(s.name)} <code>${E(s.sha256.slice(0,16))}</code></div>`).join(''):`<p>${E(t('noSources'))}</p>`}`;
  if(tab==='team')content=deliveryUI.settingsHTML(project);
  if(tab==='tasks')content=project.works.length?project.works.map(w=>`<div class="detail-card"><strong>${E(w.title)}</strong><p>${E(w.state)} · ${E(w.id)}</p><pre>${E(w.body)}</pre></div>`).join(''):`<p>${E(t('noTasks'))}</p>`;
  if(tab==='deliverables')content=project.executions.some(e=>e.state==='COMPLETED')?project.executions.filter(e=>e.state==='COMPLETED').map(e=>`<div class="detail-card"><strong>${E(e.phase)}</strong><pre>${E(e.output)}</pre></div>`).join(''):`<p>${E(t('noResults'))}</p>`;
  if(tab==='tasks'&&project.deliveries?.length)content=project.deliveries.map(d=>`<div class="detail-card"><h3>${E(d.title)}</h3><div class="markdown">${markdown(d.objective)}</div><button data-action="chat" data-id="${E(d.chat_id)}">${E(t('conversation'))}</button></div>`).join('')+content;
  if(tab==='deliverables'&&project.deliveries?.some(d=>d.files.length))content=project.deliveries.filter(d=>d.files.length).map(d=>`<div class="detail-card"><h3>${E(d.title)}</h3><div class="markdown">${markdown(d.output)}</div><a href="/api/r2/wb/deliveries/${E(d.id)}/download">${lang==='zh'?'下载成果':'Download files'}</a><details><summary>${E(t('reviewer'))}</summary><div class="markdown">${markdown(d.review)}</div></details></div>`).join('')+content;
  $('detail').innerHTML=b('back','back','class="back"')+`<h2>${E(t(tab))}</h2><p>${E(t('detailDescription'))}</p>${content}`;
 }
 async function send(){
  if(composing||sending)return;draft=$('draft').value;if(!draft.trim()&&!selected.length)return;
  sending=true;renderMessages();
  try{
   await saveDraft();await ensureChat();if(!state.connection){openConnect();return;}
   if((selected.length||search.source_ids.length)&&!$('send-consent').checked)throw new Error('CONTENT_SEND_CONSENT_REQUIRED');
   const cid=chat.id,g=generation,body=draft,attachments=[...selected],key=sendKey||crypto.randomUUID();sendKey=key;
   await api(`/api/r2/wb/chats/${cid}/send`,{body,request_id:key,attachments,...search,send_selected_content:$('send-consent').checked});
   const next=await api(`/api/r2/wb/chats/${cid}`);
   if(chat?.id!==cid||g!==generation)return;
   if(draft===body&&JSON.stringify(selected)===JSON.stringify(attachments)){draft='';selected=[];dirty=false;$('draft').value='';$('send-consent').checked=false;}
   chat=next;sendKey=null;await refreshState();if(chat?.id!==cid||g!==generation)return;
   renderTree();renderMessages();renderAttachments();renderPanes();if(dirty)await saveDraft();
  }finally{sending=false;renderMessages();}
 }
 function openConnect(repair=false){const proposed=repair?tools.candidates.find(c=>c.path.includes('/Contents/Resources/codex-cli/')||c.path.includes('/Contents/Resources/codex')):null;dialog('connectTitle',`<p>${E(t('connectDesc'))}</p><p>${E(t('authRequired'))}</p>${!tools.candidates.length?`<p>${E(t('noTools'))}</p>`:`<form id="connect-form" class="form-grid">${repair?`<p class="notice">${E(t(proposed?'connectionRepairHint':'connectionUpdateHint'))}</p>`:''}<label>${E(t('tool'))}<select id="connect-tool">${tools.candidates.map(c=>`<option value="${E(c.id)}" ${c.id===(proposed?.id||state.connection?.tool_id)?'selected':''}>${E(c.label||c.path)}</option>`).join('')}</select></label>${modelSelect('model','connect-model',state.connection?.model||'')}<p>${E(t('realIdentity'))}</p>${check('consent','connect-consent')}<button type="submit" class="primary">${E(t('connect'))}</button></form>`}`);}
 function projectDialog(save=false,importing=false){projectRequest=crypto.randomUUID();dialog(save?'saveToProject':importing?'importProject':'newProject',`<form id="project-form" class="form-grid" data-save="${save}" data-import="${importing}">${input('projectLabel','project-title')}${check('development','development')}<p>${E(t('newProjectNote'))}</p>${save&&projects.length?`<label>${E(t('projects'))}<select id="existing-project"><option value="">—</option>${projects.filter(p=>!p.legacy).map(p=>`<option value="${p.id}">${E(p.name)}</option>`).join('')}</select></label>`:''}<button type="submit" class="primary">${E(t(save?'saveToProject':'create'))}</button></form>`);}
 async function openHandoff(){await saveDraft();if(!chat)return;draft=lang==='zh'?'请根据上面的讨论整理可交给 Codex 实现的交付说明，明确要做什么、交付什么以及如何检查。':'Prepare a Codex delivery proposal from our discussion: what to implement, the deliverables, and how to check them.';dirty=true;$('draft').value=draft;await send();}
 async function openTools(){if(!project){dialog('plugins',`<p>${E(t('noSources'))}</p>`);return;}dialog('plugins',`<form id="search-form" class="form-grid"><p>${E(t('pluginDescription'))}</p>${project.sources.map(s=>`<label><input type="checkbox" name="source" value="${s.id}" ${search.source_ids.includes(s.id)?'checked':''}>${E(s.name)}</label>`).join('')}${input('query','search-query',search.search)}<button type="submit">${E(t('doneButton'))}</button></form>`);}
 async function upload(files){await ensureChat();for(const file of files){const bytes=new Uint8Array(await file.arrayBuffer());if(bytes.length>5000000)throw new Error('ATTACHMENT_TOO_LARGE');let binary='';for(let i=0;i<bytes.length;i+=16384)binary+=String.fromCharCode(...bytes.subarray(i,i+16384));const a=await api(route('/attachments'),{filename:file.name,data_base64:btoa(binary)});chat.attachments.push(a);selected.push(a.id);}dirty=true;await saveDraft();renderAttachments();}
 async function poll(){if(!state||!chat||polling)return;polling=true;const cid=chat.id,g=generation;try{const next=await api(`/api/r2/wb/chats/${cid}`);if(chat?.id!==cid||g!==generation)return;chat.messages=next.messages;chat.handoffs=next.handoffs;chat.deliveries=next.deliveries;renderMessages();renderRight();deliveryUI.prepare().catch(alertError);if(project)project=await api('/api/r2/projects/'+project.id);}catch(e){if(e.code==='CHAT_DELETED'&&chat?.id===cid){generation++;chat=null;draft='';selected=[];dirty=false;tab='';await refreshState();render();alertError(e);}else if(e.code==='HTTP_401')alertError(e);}finally{polling=false;}}
 async function execution(action,id){const w=chat.handoffs.find(h=>h.work.id===id)?.work;if(!w)return;const key=crypto.randomUUID();if(action==='plan')await api(`/api/r2/work/${id}/plan`,{});else if(action==='approve')await api(`/api/r2/work/${id}/approve`,{plan_hash:w.plan_hash,ui_locale:lang==='zh'?'zh-CN':'en-US',confirmation:true,single_model_disclosed:true});else if(action==='start'||action==='review')await api(w.kind==='iteration'?`/api/r2/iterations/${id}/${action==='review'?'review':'execute'}`:`/api/r2/work/${id}/start`,{plan_hash:w.plan_hash,request_id:key,confirmation:true});else if(action==='stop')await api(`/api/r2/work/${id}/cancel`,{});await poll();}
 document.addEventListener('click',async e=>{const n=e.target.closest('[data-action]');if(!n)return;const a=n.dataset.action;if(state&&!$('composer-area').hidden&&$('draft').value!==draft){draft=$('draft').value;dirty=true;sendKey=null;}clearAlert();try{
  if(['signup','login','reset','legacy'].includes(a)){authStep=a;renderAuth();return;}
  if(a?.startsWith('delivery-')){await deliveryUI.action(a,n);return;}
  if(a==='auth-back'){authStep='welcome';renderAuth();return;}
  if(a==='show'){const el=$(n.dataset.input);el.type=el.type==='password'?'text':'password';let label='hidePassword';if(el.type==='password')label='showPassword';n.textContent=t(label);return;}
  if(a==='resend'){await api('/api/auth/email/resend',{challenge_id:challenge});return;}
  if(a==='close'){close();return;}
  if(a==='home'){if(!state){authStep='welcome';renderAuth();return;}await saveDraft();generation++;chat=null;project=null;draft='';selected=[];dirty=false;tab='';search={source_ids:[],search:''};render();await saveLayout();}
  if(a==='chat')await selectChat(n.dataset.id);
  if(a==='chat-menu'){const c=state.chats.find(c=>c.id===n.dataset.id);if(c)dialog('chatOptions',`<p>${E(c.title||t('newMessage'))}</p>`,b('deleteChat','delete-chat',`data-id="${E(c.id)}"`));}
  if(a==='delete-chat')dialog('deleteChat',`<p>${E(t('deleteChatNote'))}</p>`,b('deleteChat','confirm-delete-chat',`data-id="${E(n.dataset.id)}" class="danger"`));
  if(a==='confirm-delete-chat')await deleteChat(n.dataset.id);
  if(a==='deleted-chats'){await refreshState();deletedChats();}
  if(a==='restore-chat'){await api(`/api/r2/wb/chats/${n.dataset.id}/restore`,{confirmation:true});await refreshState();renderTree();deletedChats();}
  if(a==='copy-message'){const m=chat?.messages.find(m=>m.id===n.dataset.id);if(m){await navigator.clipboard.writeText(m.body);n.textContent=t('copied');}}
  if(a==='enable-development')dialog('enableDevelopment',`<p>${E(t('enableDevelopmentNote'))}</p>`,b('confirmEnableDevelopment','confirm-development','class="primary"'));
  if(a==='confirm-development'){await api(`/api/r2/wb/projects/${project.id}/enable-development`,{confirmation:true});project=await api('/api/r2/projects/'+project.id);close();renderDetail();}
  if(a==='project')await selectProject(Number(n.dataset.id));
  if(a==='new-chat'){await saveDraft();generation++;chat=null;draft='';selected=[];search={source_ids:[],search:''};dirty=false;tab='';await ensureChat();render();}
  if(a==='new-project'||a==='import-project'||a==='save-project'){await saveDraft();projectDialog(a==='save-project',a==='import-project');}
  if(a==='connect'||a==='repair-connection'){await saveDraft();tools=await api('/api/r2/tools');openConnect(a==='repair-connection');}if(a==='tools')await openTools();if(a==='handoff')await openHandoff();
  if(a==='send')await send();if(a==='cancel-discussion')await api(route('/cancel'),{});
  if(a==='attach')$('file-input').click();if(a==='remove'){selected=selected.filter(id=>id!==n.dataset.id);dirty=true;await saveDraft();renderAttachments();}
  if(a==='tab'||a==='back'){await saveDraft();if(!tab)workbenchScroll=$('chat-region').scrollTop;tab=a==='back'?'':n.dataset.tab;renderDetail();if(!tab)$('chat-region').scrollTop=workbenchScroll;await saveLayout();}
  if(a==='pane'){const pane=n.dataset.pane;if(hidden.includes(pane))hidden=hidden.filter(p=>p!==pane);else if(hidden.length<2)hidden.push(pane);renderPanes();await saveLayout();}
  if(a==='mobile'){mobile=n.dataset.pane;renderPanes();}
  if(a==='account')dialog('accountTitle',`<p>${E(state.user.name)}</p><p>${E(t('accountNote'))}</p>`,b('bind','bind')+b('deletedChats','deleted-chats')+b('signOut','logout'));
  if(a==='bind')dialog('bind',`<form id="bind-form" class="form-grid">${input('email','bind-email','', 'email')}${input('password','bind-password','','password')}<button type="submit">${E(t('sendCode'))}</button></form>`);
  if(a==='logout'){await saveDraft();await api('/api/auth/logout',{});generation++;state=null;chat=null;project=null;draft='';selected=[];close();authStep='welcome';renderAuth();}
  if(a==='replan')dialog('replan',`<p>${E(t('replanNote'))}</p>`,b('confirmReplan','confirm-replan',`data-work="${E(n.dataset.work)}" class="primary"`));
  if(a==='confirm-replan'){const w=chat.handoffs.find(h=>h.work.id===n.dataset.work)?.work;if(w){await api(`/api/r2/iterations/${w.id}/revision/plan`,{body:w.body,output_locale:w.output_locale,request_id:crypto.randomUUID(),expected_revision:w.revision,confirmation:true});close();await poll();}}
  if(['plan','approve','start','review','stop'].includes(a))await execution(a,n.dataset.work);
  if(a==='import-sources')dialog('upload',`<form id="import-form" class="form-grid"><p>${E(t('importBoundary'))}</p><input id="source-file" type="file" accept=".txt,.md,.zip" required><button type="submit">${E(t('continue'))}</button></form>`);
  if(a==='confirm-import'){const names=[...$('dialog').querySelectorAll('input[name=import]:checked')].map(el=>el.value);await api(`/api/r2/projects/${project.id}/imports/${importPreview.preview_id}/confirm`,{sha256:importPreview.sha256,names,confirmation:true});close();project=await api('/api/r2/projects/'+project.id);renderDetail();}
  if(a==='target-confirm'){await api(`/api/r2/projects/${project.id}/target/confirm`,{preview_hash:targetPreview.preview_hash,confirmation:true});close();project=await api('/api/r2/projects/'+project.id);renderDetail();}
 }catch(error){alertError(error);}});
 document.addEventListener('submit',async e=>{e.preventDefault();const form=e.target;const buttons=[...form.querySelectorAll('button[type=submit]')];buttons.forEach(b=>b.disabled=true);clearAlert();try{
  if(await deliveryUI.submit(form))return;
  if(form.id==='auth-form')await submitAuth();
  if(form.id==='connect-form'){await api('/api/r2/wb/connect',{tool_id:$('connect-tool').value,model:$('connect-model').value,confirmation:$('connect-consent').checked,existing_plan_only:true});await refreshState();close();render();}
  if(form.id==='project-form'){await saveDraft();const existing=$('existing-project')?.value;const pid=existing?Number(existing):(await api('/api/r2/wb/projects',{name:$('project-title').value,request_id:projectRequest,kind:$('development').checked?'development':'blank'})).id;if(form.dataset.save==='true'&&chat)await api(route('/assign'),{project_id:pid,confirmation:true});const importing=form.dataset.import==='true';close();await refreshState();if(form.dataset.save==='true'&&chat)await selectChat(chat.id,false);else await selectProject(pid);if(importing){tab='sources';renderDetail();}}
  if(form.id==='search-form'){search={source_ids:[...form.querySelectorAll('input[name=source]:checked')].map(el=>el.value),search:$('search-query').value};dirty=true;await saveDraft();close();renderAttachments();}
  if(form.id==='team-form'){await api(`/api/r2/projects/${project.id}/team`,{tool_id:$('team-tool').value,planner:$('planner').value,executor:$('executor').value,reviewer:$('reviewer').value,existing_plan_only:$('team-consent').checked,human_gates:project.team?.human_gates||[]});project=await api('/api/r2/projects/'+project.id);renderDetail();}
  if(form.id==='target-form'){targetPreview=await api(`/api/r2/projects/${project.id}/target/preview`,{path:$('target-path').value});dialog('targetPreview',`<pre>${E(JSON.stringify(targetPreview,null,2))}</pre>`,b('targetConfirm','target-confirm'));}
  if(form.id==='handoff-form'){await api(route('/handoffs'),{request_id:crypto.randomUUID(),kind:$('handoff-kind').value,instruction:$('handoff-instruction').value,output_locale:lang==='zh'?'zh-CN':'en-US',confirmation:$('handoff-consent').checked});close();hidden=hidden.filter(p=>p!=='right');await poll();renderPanes();}
  if(form.id==='import-form'){const file=$('source-file').files[0];const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=16384)binary+=String.fromCharCode(...bytes.subarray(i,i+16384));importPreview=await api(`/api/r2/projects/${project.id}/imports/preview`,{filename:file.name,data_base64:btoa(binary)});dialog('importProject',`<p>${E(t('importBoundary'))}</p>${importPreview.entries.map(x=>`<label class="source-row"><input type="checkbox" name="import" value="${E(x.name)}" ${x.classification==='SAFE_IMPORT'?'':'disabled'}>${E(x.name)} · ${E(x.classification)}</label>`).join('')}`,b('confirmImport','confirm-import'));}
  if(form.id==='bind-form'){authEmail=$('bind-email').value;const r=await api('/api/auth/email/begin',{email:authEmail,purpose:'bind',password:$('bind-password').value,confirmation:true});challenge=r.challenge_id;dialog('verifyTitle',`<form id="bind-verify" class="form-grid">${input('code','bind-code')}<button type="submit">${E(t('verifyEmail'))}</button></form>`);}
  if(form.id==='bind-verify'){await api('/api/auth/email/verify',{challenge_id:challenge,purpose:'bind',code:$('bind-code').value});dialog('bindConfirm',`<form id="bind-confirm" class="form-grid"><p>${E(authEmail)}</p><button type="submit">${E(t('bindConfirm'))}</button></form>`);}
  if(form.id==='bind-confirm'){await api('/api/auth/email/bind/confirm',{challenge_id:challenge,confirmation:true});close();await refreshState();}
 }catch(error){alertError(error);}finally{buttons.forEach(b=>b.disabled=false);}});
 $('draft').addEventListener('input',()=>{draft=$('draft').value;dirty=true;sendKey=null;clearTimeout(saveTimer);saveTimer=setTimeout(()=>saveDraft().catch(alertError),350);});
 $('draft').addEventListener('compositionstart',()=>composing=true);$('draft').addEventListener('compositionend',()=>composing=false);
 $('draft').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&!composing&&e.keyCode!==229){e.preventDefault();send().catch(alertError);}});
 $('file-input').onchange=async e=>{try{await upload([...e.target.files]);}catch(error){alertError(error);}finally{e.target.value='';}};
 $('lang').onchange=async e=>{const next=e.target.value;try{await saveDraft();await api('/api/r2/preferences',{locale:next==='zh'?'zh-CN':'en-US'});lang=next;render();}catch(error){alertError(error);}};
 for(const divider of document.querySelectorAll('[data-resize]')){const side=divider.dataset.resize;const resize=delta=>{if(side==='left')left=Math.max(180,Math.min(360,left+delta));else right=Math.max(280,Math.min(600,right-delta));renderPanes();};divider.onpointerdown=e=>{divider.setPointerCapture(e.pointerId);let previous=e.clientX;divider.onpointermove=x=>{resize(x.clientX-previous);previous=x.clientX;};divider.onpointerup=()=>{divider.onpointermove=null;saveLayout().catch(alertError);};};divider.onkeydown=e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();resize(e.key==='ArrowRight'?20:-20);saveLayout().catch(alertError);}};}
 window.addEventListener('pagehide',()=>{if(state&&chat&&dirty){fetch(`/api/r2/wb/chats/${chat.id}/draft`,{method:'POST',credentials:'same-origin',keepalive:true,headers:{'Content-Type':'application/json'},body:JSON.stringify({body:$('draft').value,attachments:selected,version:chat.draft_version,...search})}).catch(()=>{});}});
 document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden'){saveDraft().catch(()=>{});saveLayout().catch(()=>{});}});
 fetch($('workbench-script').dataset.catalog,{cache:'no-store'}).then(r=>r.json()).then(data=>{D=data;return initialize();}).catch(alertError);
 setInterval(poll,1500);
})();
