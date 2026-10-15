/* Continuous Codex UI. Configuration animation follows actual saved operations. */
window.TWOSDelivery = function(ctx) {
 'use strict';
 const {api,E,markdown}=ctx, $=id=>document.getElementById(id);
 const L=(en,zh)=>ctx.lang()==='zh'?zh:en;
 let configuring=null, dismissed=false, importPreview=null;
 const keys=new Map(), setupFailures=new Set();
 const key=id=>{if(!keys.has(id))keys.set(id,crypto.randomUUID());return keys.get(id);};
 const button=(label,action,id,extra='')=>`<button data-action="delivery-${action}" data-id="${E(id)}" ${extra}>${E(label)}</button>`;
 const rows=()=>ctx.chat()?.deliveries||[];
 const active=d=>['QUEUED','RUNNING','REVIEWING','WAITING_APPROVAL'].includes(d.state);
 function proposal(d){
  const s=d.specification,c=d.configuration;
  if(s.kind==='configuration'){return ['PROPOSED','CONFIGURED'].includes(d.state)?`<section class="delivery-proposal" data-delivery="${E(d.id)}"><p>${E(d.state==='CONFIGURED'?L('Configuration saved. You can change it in AI team.','配置已保存，以后可在「AI 团队」修改。'):L('Preparing the requested configuration…','正在准备你要求的配置…'))}</p>${button(L('AI team','AI 团队'),'settings',d.id)}${setupFailures.has(d.id)?button(L('Continue setup','继续配置'),'setup',d.id):''}</section>`:'';}
  if(!['PROPOSED','READY'].includes(d.state))return '';
  return `<section class="delivery-proposal" data-delivery="${E(d.id)}"><h3>${E(s.title)}</h3><p class="delivery-label">${L('You will receive','你将得到')}</p><ul>${s.deliverables.map(x=>`<li>${E(x)}</li>`).join('')}</ul><details><summary>${L('Task, checks and working environment','任务、检查方式与工作环境')}</summary><div class="markdown">${markdown(s.objective)}</div><ul>${s.checks.map(x=>`<li>${E(x)}</li>`).join('')}</ul><p>${E(c.executor||'')} · ${L('Automatic independent review','自动独立复核')}</p><p class="workspace-path">${E(c.workspace||L('Preparing your project…','正在准备项目…'))}</p></details>${setupFailures.has(d.id)?button(L('Continue setup','继续配置'),'setup',d.id):''}<div class="toolbar">${button(L('Hand to Codex','交给 Codex'),'approve',d.id,`class="primary" ${d.state==='READY'?'':'disabled'}`)}${button(L('Reject','暂不执行'),'reject',d.id,d.state==='READY'?'':'disabled')}${button(L('Other comments','补充意见'),'comment',d.id)}</div><p class="quiet-note">${L('This starts the work described above. Progress and decisions appear on the right.','点击后即开始上面的工作，进展和需要你决定的事项会出现在右栏。')}</p></section>`;
 }
 function proposals(){return rows().map(proposal).join('');}
 function settingsHTML(project){
  const c=project.integrated||{},team=c.team||{},connection=ctx.connection()||{};
  const select=(role,label)=>`<label>${label}<select id="integrated-${role}" class="model-select">${[...new Set([connection.model,...(ctx.models()||[]),team[role]].filter(Boolean))].sort((a,b)=>a==='gpt-6.1-sol'?-1:b==='gpt-6.1-sol'?1:a.localeCompare(b)).map(m=>`<option ${m===(team[role]||connection.model)?'selected':''}>${E(m)}</option>`).join('')}</select></label>`;
  return `<p>${L('TWOS prepares these settings for your task. You can change them here at any time.','TWOS 会按任务自动准备配置；以后随时可以在这里修改。')}</p><form id="integrated-team-form" class="form-grid">${select('planner',L('Discussion & planning','讨论与规划'))}${select('executor',L('Implementation','开发执行'))}${select('reviewer',L('Independent review','独立复核'))}<p class="quiet-note">${L('Uses your connected account. Quotas come from the provider; TWOS adds no call limit.','使用已连接账号，额度以服务商为准，TWOS 不另设调用次数上限。')}</p><button type="submit" id="integrated-save" class="primary">${L('Save changes','保存修改')}</button></form><section id="integrated-workspace"><h3>${L('Working environment','工作环境')}</h3><p>${L('A separate local project. Your original files remain intact.','独立的本机项目目录，原始文件保留。')}</p><p class="workspace-path">${E(c.workspace?.path||L('Created automatically for your first delivery','首次交付时自动创建'))}</p>${Object.entries(c.workspace?.tools||{}).map(([name,path])=>`<p class="runtime-tool"><strong>${E(name)}</strong> <span class="workspace-path">${E(path)}</span></p>`).join('')}${button(L('Continue from existing source…','从已有源码继续…'),'import',String(project.id))}<input id="delivery-folder" type="file" webkitdirectory multiple hidden></section>`;
 }
 function hint(text){
  let el=$('configuration-guide');
  if(!el){el=document.createElement('aside');el.id='configuration-guide';el.setAttribute('role','status');document.body.append(el);}
  el.innerHTML=`<span>${E(text)}</span>${button(L('Back to chat','回到对话'),'dismiss','')}`;
 }
 const pause=()=>new Promise(resolve=>setTimeout(resolve,450));
 async function prepare(){
  const d=rows().find(d=>d.state==='PROPOSED'&&!setupFailures.has(d.id));
  if(!d||configuring)return;
  configuring=d.id;dismissed=false;const cid=ctx.chat().id;
  const visible=()=>ctx.chat()?.id===cid&&!dismissed;
  try{
   for(const step of ['project','team','workspace']){
    if(d.configuration.setup_done?.includes(step))continue;
    if(visible())hint(({project:L('Preparing your project…','正在准备项目…'),team:L('AI team → choosing the models. You can change them here later.','AI 团队 → 正在选择模型，以后可在这里修改。'),workspace:L('Working environment → preparing your project directory.','工作环境 → 正在准备项目目录。')})[step]);
    if(step==='team'&&visible()){
     ctx.navigate('team');await pause();
     for(const role of ['planner','executor','reviewer']){
      const field=$('integrated-'+role);if(field){const value=d.specification.team?.[role]||field.value;if(![...field.options].some(o=>o.value===value))field.add(new Option(value,value));field.selectedIndex=-1;field.focus();field.classList.add('configuration-focus');await pause();field.value=value;field.dispatchEvent(new Event('change',{bubbles:true}));await pause();field.classList.remove('configuration-focus');}
     }
     $('integrated-save')?.classList.add('configuration-focus');
    }
    const saved=await api(`/api/r2/wb/deliveries/${d.id}/setup`,{step});
    Object.assign(d,saved);await ctx.refresh(cid);
    if(visible()){
     if(step!=='project')ctx.navigate('team');
     if(step==='workspace')$('integrated-workspace')?.scrollIntoView({block:'center',behavior:'smooth'});
     hint(L('Saved. You can update this in AI team.','已保存。以后可在「AI 团队」更新这里的配置。'));await pause();
    }
   }
   if(visible()){ctx.navigate('');ctx.render();}
  }catch(error){setupFailures.add(d.id);ctx.error(error);if(visible())hint(L('Setup stopped here. Your conversation is saved; retry when ready.','配置停在当前步骤，对话已保存。处理提示后可继续。'));}
  finally{configuring=null;$('configuration-guide')?.remove();}
 }
 function approvals(d){
  const answered=new Set(d.events.filter(e=>e.kind==='approval_answered').map(e=>e.payload.event_id));
  const resolved=new Set(d.events.filter(e=>e.kind==='serverRequest/resolved').map(e=>e.payload.requestId));
  return d.events.filter(e=>e.kind==='approval'&&!answered.has(e.id)&&!resolved.has(e.payload.request_id)&&e.payload.params.threadId===d.thread_id&&e.payload.params.turnId===d.turn_id&&active(d)).map(e=>{
   const p=e.payload.params,questions=p.questions||[];
   const permissions=p.permissions||p.additionalPermissions||{},fs=permissions.fileSystem||permissions.file_system||{};
   const scope=[...(fs.read||[]),...(fs.write||[]),...(fs.entries||[]).map(x=>x.path?.path||'')].filter(Boolean);
   const access=`${p.cwd?`<p class="workspace-path">${E(p.cwd)}</p>`:''}${scope.length?`<ul>${scope.map(x=>`<li>${E(x)}</li>`).join('')}</ul>`:''}${permissions.network?.enabled?`<p>${L('Requests network access for this turn','请求在本轮使用网络')}</p>`:''}`;
   return `<section class="codex-approval"><h4>${L('Your decision','需要你决定')}</h4><p>${E(p.reason||p.command||L('Codex needs your input to continue.','Codex 需要你的意见才能继续。'))}</p>${p.command?`<pre>${E(p.command)}</pre>`:''}${access}${questions.map(q=>`<label>${E(q.question)}<textarea data-question="${E(q.id)}" data-event="${e.id}" placeholder="${E((q.options||[]).map(o=>o.label).join(' / '))}"></textarea></label>`).join('')}<textarea id="decision-comment-${e.id}" placeholder="${L('Other comments (optional)','其他意见（可选）')}"></textarea><div class="toolbar">${button(L('Approve','批准'),'answer',d.id,`data-event="${e.id}" data-decision="approve" class="primary"`)}${button(L('Reject','拒绝'),'answer',d.id,`data-event="${e.id}" data-decision="reject"`)}${button(L('Send comments','发送意见'),'answer',d.id,`data-event="${e.id}" data-decision="comment"`)}</div></section>`;
  }).join('');
 }
 function deliveryMarkdown(text,d){
  const files=d.events.filter(e=>e.kind==='artifacts').at(-1)?.payload.files||[],links=Object.create(null);
  for(const f of files){
   const url=`/api/r2/wb/deliveries/${encodeURIComponent(d.id)}/files/${f.path.split('/').map(encodeURIComponent).join('/')}`;
   for(const path of [f.path,'./'+f.path,(d.configuration.workspace||'')+'/'+f.path]){links[path]=url;links[encodeURI(path)]=url;}
  }
  return markdown(text,links);
 }
 function timeline(d){
  const items=new Map();
  for(const e of d.events){const p=e.payload;
   if(e.kind==='item/started'||e.kind==='item/completed'){
    const item=p.item||{};if(item.id)items.set(item.id,{...(items.get(item.id)||{}),...item,phase:p.phase});
   }else if(e.kind==='item/agentMessage/delta'){
    const item=items.get(p.itemId)||{id:p.itemId,type:'agentMessage',text:'',phase:p.phase};item.text=(item.text||'')+p.delta;items.set(p.itemId,item);
   }else if(e.kind==='item/commandExecution/outputDelta'){
    const item=items.get(p.itemId)||{id:p.itemId,type:'commandExecution',command:'',phase:p.phase};item.aggregatedOutput=(item.aggregatedOutput||'')+p.delta;items.set(p.itemId,item);
   }else if(e.kind==='user_comment'){items.set('event:'+e.id,{type:'userComment',text:p.text});}
   else if(['warning','error','steer_failed'].includes(e.kind)){const text=e.kind==='steer_failed'?L('Your new instructions were not accepted by Codex. Send them again after this turn.','Codex 未接收刚才的补充指令，请在本轮结束后重新发送。'):typeof p.message==='string'?p.message:p.error?.message;if(text)items.set('event:'+e.id,{type:'notice',text});}
  }
  return [...items.values()].map(i=>{
   if(i.type==='userComment')return `<div class="codex-user">${E(i.text)}</div>`;
   if(i.type==='notice')return `<p class="quiet-note">${E(i.text)}</p>`;
   if(i.type==='agentMessage')return `<article class="codex-message"><div class="phase-caption">${i.phase==='review'?L('Review','复核'):''}</div><div class="markdown">${deliveryMarkdown((i.text||'').split('```twos-review')[0],d)}</div></article>`;
   if(i.type==='commandExecution')return `<details class="codex-tool" data-detail="${E(d.id+':'+i.id)}"><summary>${E(i.command||L('Running command','正在运行命令'))}${i.exitCode!==undefined&&i.exitCode!==null?` · ${L('exit','退出码')} ${E(i.exitCode)}`:''}</summary><pre>${E(i.aggregatedOutput||'')}</pre></details>`;
   if(i.type==='fileChange')return `<details class="codex-tool" data-detail="${E(d.id+':'+i.id)}"><summary>${L('Changed files','文件修改')} · ${E((i.changes||[]).map(c=>c.path.split('/').at(-1)).join(', '))}</summary>${(i.changes||[]).map(c=>`<p>${E(c.path)}</p><pre>${E(c.diff||'')}</pre>`).join('')}</details>`;
   if(i.type==='plan')return `<div class="markdown">${deliveryMarkdown((i.text||'').split('```twos-review')[0],d)}</div>`;
   return '';
  }).join('');
 }
 function panel(){
  if(!rows().length)return '';
  return rows().filter(d=>d.specification.kind!=='configuration'&&!['SUPERSEDED','REJECTED'].includes(d.state)).map(d=>{
   const status=({PROPOSED:L('Preparing','准备中'),READY:L('Waiting for your handoff','等你确认交付'),QUEUED:L('Starting Codex…','正在启动 Codex…'),RUNNING:L('Working…','正在处理…'),REVIEWING:L('Reviewing automatically…','正在自动复核…'),WAITING_APPROVAL:L('Your decision is needed','等待你的决定'),COMPLETED:L('Finished · review returned','已完成 · 复核已返回'),INTERRUPTED:L('Interrupted · progress saved','已中断 · 进度已保存'),CANCELLED:L('Stopped','已停止'),NEEDS_ATTENTION:L('Needs attention','需要处理')})[d.state]||'';
   const quotaEvent=d.events.filter(e=>e.kind==='account/rateLimits/updated').at(-1)?.payload||{};
   const limits=quotaEvent.rateLimitsByLimitId?Object.values(quotaEvent.rateLimitsByLimitId):quotaEvent.rateLimits?[quotaEvent.rateLimits]:[];
   const quota=limits.flatMap(q=>['primary','secondary'].map(k=>q[k]).filter(q=>q&&Number.isFinite(q.usedPercent))).map(q=>`<p>${L('Provider usage','服务商用量')} ${E(q.usedPercent)}%${q.resetsAt?` · ${L('Resets','重置时间')} ${E(new Date(q.resetsAt*1000).toLocaleString())}`:''}</p>`).join('');
   const files=d.events.filter(e=>e.kind==='artifacts').at(-1)?.payload.files||[];
   const artifacts=files.filter(f=>/\.(html|md|txt|pdf|png|csv|json)$/.test(f.path)).slice(0,16);
   return `<section class="codex-delivery"><h3>${E(d.specification.title)}</h3><p class="quiet-note" role="status">${E(status)}</p>${timeline(d)}${approvals(d)}${quota?`<details class="provider-quota"><summary>${L('Provider allowance','服务商额度')}</summary>${quota}</details>`:''}${d.error_code?`<p class="notice">${E(errorText(d.error_code))}</p>`:''}${files.length?`<div class="artifact-links">${artifacts.map(f=>`<a href="/api/r2/wb/deliveries/${d.id}/files/${f.path.split('/').map(encodeURIComponent).join('/')}" target="_blank" rel="noopener">${E(f.path)}</a>`).join('')}<a href="/api/r2/wb/deliveries/${d.id}/download">${L('Download project','下载项目')}</a></div>`:''}${active(d)?button(L('Stop','停止'),'stop',d.id):''}${d.error_code==='REVIEW_CHANGES_REQUIRED'?button(L('Discuss the findings','讨论如何修改'),'comment',d.id):['RUNNING','REVIEWING','NEEDS_ATTENTION','INTERRUPTED','CANCELLED'].includes(d.state)?`<form class="codex-followup" data-delivery="${d.id}"><textarea name="body" required placeholder="${L('Add instructions or continue from here…','补充指令，或从这里继续…')}"></textarea><button type="submit">${L('Send','发送')}</button></form>`:''}</section>`;
  }).join('');
 }
 function errorText(code){
  if(code==='CODEX_IMPLEMENTATION_NOT_OBSERVED')return L('Codex replied without a verified file implementation. The reply is saved; this delivery is not complete. Continue here to finish the actual work.','Codex 返回了答复，但没有可验证的文件实现。答复已保存，交付尚未完成，可在这里继续完成实际制作。');
  if(code==='REVIEW_CHANGES_REQUIRED')return L('Review found issues to resolve. Files and findings are saved; discuss the changes in the conversation.','复核发现需要修正的问题。文件和意见已保存，可在对话中继续修改。');
  if(code==='REVIEW_NOT_VERIFIED')return L('Review could not verify the result. Progress is saved; continue when the missing checks can run.','复核尚未验证结果。进度已保存，具备检查条件后可继续。');
  if(code==='PROVIDER_ALLOWANCE_UNAVAILABLE')return L('The connected provider reports that its allowance is unavailable. Your progress is saved. Continue here when the provider allows it.','所连接服务商返回额度暂不可用，当前进度已保存。额度恢复后可在这里继续。');
  return ctx.errorText(code)||L('Work paused; your progress is saved. You can continue here.','工作已暂停，进度已保存，可在这里继续。');
 }
 async function action(a,n){
  const id=n.dataset.id,d=rows().find(x=>x.id===id);
  if(a==='delivery-settings'){ctx.navigate('team');return;}
  if(a==='delivery-setup'){setupFailures.delete(id);await prepare();return;}
  if(a==='delivery-dismiss'){dismissed=true;$('configuration-guide')?.remove();ctx.navigate('');return;}
  if(a==='delivery-comment'){ctx.comment(L('Please update the delivery: ','请更新交付方案：'));return;}
  if(a==='delivery-import'){const field=$('delivery-folder');if(field){field.onchange=()=>importFolder([...field.files]).catch(ctx.error);field.click();}return;}
  if(a==='delivery-import-approve'&&importPreview){await api(`/api/r2/wb/projects/${ctx.project().id}/source/confirm`,{preview_id:importPreview.id,sha256:importPreview.sha256,confirmation:true});importPreview=null;ctx.closeDialog();await ctx.refresh();hint(L('Source copied into your working environment. Original files stay unchanged.','源码已复制到工作环境，原始文件保持不变。'));setTimeout(()=>$('configuration-guide')?.remove(),3000);return;}
  if(!d)return;
  if(a==='delivery-approve'||a==='delivery-reject'){
   n.disabled=true;try{await api(`/api/r2/wb/deliveries/${id}/decide`,{decision:a==='delivery-approve'?'approve':'reject',approval_hash:d.approval_hash,request_id:key(id+':decide')});await ctx.refresh();ctx.showRight();}finally{n.disabled=false;}
  }
  if(a==='delivery-stop'){await api(`/api/r2/wb/deliveries/${id}/stop`,{});await ctx.refresh();}
  if(a==='delivery-answer'){
   const eid=Number(n.dataset.event),answers={};document.querySelectorAll(`[data-question][data-event="${eid}"]`).forEach(q=>{if(q.value.trim())answers[q.dataset.question]=[q.value];});
   await api(`/api/r2/wb/deliveries/${id}/respond`,{event_id:eid,decision:n.dataset.decision,comment:$('decision-comment-'+eid).value,answers});await ctx.refresh();
  }
 }
 async function importFolder(files){
  if(!files.length)return;
  const ignored=new Set(['.git','.codex','.aws','.ssh','.venv','node_modules','__pycache__','data','records','backups','acceptance_inputs']);
  const payload=[];let bytes=0;
  hint(L('Reading your selected source folder…','正在读取你选中的源码目录…'));
  try{
   for(const f of files){
    const parts=(f.webkitRelativePath||f.name).split('/').slice(1),path=parts.join('/');
    if(!path||parts.some(p=>ignored.has(p)||p.startsWith('.env')))continue;
    if(!/\.(py|js|ts|jsx|tsx|html|css|json|toml|yaml|yml|md|txt|sh|swift|sql|csv|lock|svg|xml|ini|cfg)$/i.test(path)&&!['Makefile','Dockerfile','.gitignore'].includes(parts.at(-1)))continue;
    bytes+=f.size;if(f.size>2000000||bytes>30000000||payload.length>=2000)throw new Error('SOURCE_TOO_LARGE');
    const data=new Uint8Array(await f.arrayBuffer());let binary='';for(let i=0;i<data.length;i+=16384)binary+=String.fromCharCode(...data.subarray(i,i+16384));
    payload.push({path,data:btoa(binary)});
   }
   importPreview=await api(`/api/r2/wb/projects/${ctx.project().id}/source/preview`,{files:payload});
   ctx.dialog(L('Use this source copy?','使用这份源码副本？'),`<p>${L('Files will be copied into this project. The original folder will not be modified.','文件将复制到本项目，原始目录不会被修改。')}</p><p>${importPreview.files.length} ${L('source files','个源码文件')} · ${L('Sensitive and generated paths excluded','已排除敏感路径与生成目录')}</p><details><summary>${L('Included files','包含的文件')}</summary>${importPreview.files.map(f=>`<div>${E(f.path)}</div>`).join('')}</details>`,button(L('Approve','批准'),'import-approve','', 'class="primary"'));
  }finally{$('configuration-guide')?.remove();}
 }
 async function submit(form){
  if(form.id==='integrated-team-form'){
   await api(`/api/r2/wb/projects/${ctx.project().id}/configuration`,{planner:$('integrated-planner').value,executor:$('integrated-executor').value,reviewer:$('integrated-reviewer').value});await ctx.refresh();hint(L('Saved in AI team. New handoffs will use these models.','已保存在 AI 团队，新的交付将使用这些模型。'));setTimeout(()=>$('configuration-guide')?.remove(),3000);return true;
  }
  if(form.matches('.codex-followup')){await api(`/api/r2/wb/deliveries/${form.dataset.delivery}/continue`,{body:form.elements.body.value,request_id:key(form.dataset.delivery+':'+form.elements.body.value)});form.reset();await ctx.refresh();return true;}
  return false;
 }
 return {proposals,panel,prepare,action,submit,settingsHTML,configuring:()=>!!configuring};
};
