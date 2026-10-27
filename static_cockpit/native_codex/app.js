'use strict';
(() => {
 const $=id=>document.getElementById(id), esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const post=(action,extra={})=>window.webkit.messageHandlers.twosCodex.postMessage({action,...extra});
 let controllable=false, controlVerified=false, submitting=false, catalog=[], folderToken='', handoffHash='', composing=false, compositionEndedAt=-Infinity, desiredModel='', desiredEffort='';
 let retryNotice=false,nyraState={available:false},resultReceipt={};
 let businessResult='', transport='', awaitingTurn=false, stopRequested=false, waitingRequests=0, answeringRequests=0, actualCwd='', actualModel='', activeTurn='', queuePaused=false;
 const detailState=new Map(), threadRecords=new Map();
 let zh=false, connected=false, busy=false, desktop=false, uncertain=false, historyReady=false, resultAvailable=false, selected='', savedThread='', draftTimer, lastFinal='', source='', items=new Map();
 const t=(en,cn)=>zh?cn:en;
 function showNotice(text,detail=''){
  retryNotice=false;
  $('notice-text').textContent=text;$('notice-detail').textContent=detail;$('notice-details').hidden=!detail;$('notice').hidden=false;
 }
 const markdown=x=>window.twosMarkdown(String(x??''));
 const summaryText=x=>(Array.isArray(x)?x:[]).map(v=>typeof v==='string'?v:v.text||'').join('\n');
 function labels(){
  $('pet-control').textContent=nyraState.available?(nyraState.visible?t('Hide Nyra','隐藏夜璃 · Nyra'):t('Show Nyra','显示夜璃 · Nyra')):t('Nyra · view status','夜璃 · 查看状态');
  $('pet-control').setAttribute('aria-label',$('pet-control').textContent);
  $('pet-control').disabled=!!nyraState.pending;
  $('pet-heading').textContent=t('Nyra · TWOS companion','夜璃 · TWOS 官方桌宠');
  $('pet-reason').textContent=nyraState.available?t('Hover over Nyra and open + for the control ring: drag, resize, outfits, actions, fullscreen and sound.','悬停夜璃并打开＋控制环：拖动、缩放、换装、动作、全屏与声音。'):t('The Nyra helper is not available here. No visibility change is claimed.','此实例的夜璃辅助程序暂不可用，未宣称改变显示状态。')+(nyraState.reason?' · '+nyraState.reason:'');
  $('pet-binding').textContent=(nyraState.binding==='CONNECTED_READONLY'?t('Connected to this TWOS instance: read-only task status. ','已连接此 TWOS 实例：只读任务状态。'):t('Task status is not connected. ','尚未关联任务状态。'))+t('Separate native floating window. Animations do not prove execution or acceptance. These controls do not call a model.','独立原生浮窗。动画不代表执行或验收；这些控件不会调用模型。');
  for(const [id,en,cn] of [['refresh','Refresh','刷新会话'],['draft','Message','消息'],['model','Model','模型'],['effort','Reasoning level','推理档位'],['mode','Input mode','输入模式'],['timeline','Conversation','对话'],['telemetry','Usage and run observations','用量与运行观测'],['result-files','Workspace files','工作目录文件']])$(id).setAttribute('aria-label',t(en,cn));

  $('workbench-title').textContent='Codex';$('binding').textContent=t('Local workspace','本机工作区');$('connect').textContent=t('Connect local Codex','连接本机 Codex');
  $('workspace').textContent=t('Open workspace','打开工作目录');$('more-threads').textContent=t('More','更多会话');$('reconnect').textContent=t('Reconnect and inspect','重新连接并查看');$('details-label').textContent=t('Details','消息详情');
  $('thread-label').textContent=t('Conversation','会话');$('empty')&&($('empty').textContent=t('Connect to choose an existing local conversation. Selecting a conversation does not execute it.','连接后选择已有本机会话。选择会话不会开始执行。'));
  $('draft').placeholder=t('Ask Codex to do something…','让 Codex 做点什么…');$('stop').textContent=t('Stop','停止');$('send').textContent='↑';
  $('send').setAttribute('aria-label',t('Send','发送'));$('attach').setAttribute('aria-label',t('Add files or images','添加文件或图片'));
  $('keyboard-help').textContent=t('Enter to send · Shift+Enter for a new line','Enter 发送 · Shift+Enter 换行');$('latest').textContent=t('↓ Latest messages','↓ 回到最新消息');$('notice-close').setAttribute('aria-label',t('Dismiss notice','收起提示'));
  $('more').textContent=t('Older messages','更早消息');$('return').textContent=t('Return result to discussion','将结果带回原讨论');
  for(const [id,label] of [['threads',t('Choose existing conversation','选择已有会话')],['model',t('Keep conversation model','沿用会话模型')]]){const empty=Array.from($(id).options).find(x=>!x.value);if(empty)empty.textContent=label;}
  for(const [id,en,cn] of [['new-task','New task / conversation','新建任务 / 会话'],['task-title','Choose the task folder','选择任务目录'],['directory-mode-label','Folder mode','目录模式'],['choose-folder','Choose folder','选择文件夹'],['create-folder','Create folder','新建文件夹'],['confirm-folder','Confirm folder and create task','确认目录并创建任务'],['cancel-folder','Cancel','取消'],['task-model-label','Model','模型'],['task-effort-label','Reasoning','推理档位'],['handoff-title','Send to Codex','交付 Codex 执行'],['handoff-preview-label','Full instruction preview','完整指令预览'],['handoff-new','New task / choose folder','新建任务 / 选择目录'],['cancel-handoff','Cancel','取消'],['queue-title','Queued inputs','后续输入'],['resume-queue','Continue queue','继续队列'],['inspect-delivery','Inspect delivery','核验送达']])$(id).textContent=t(en,cn);
  $('directory-mode').options[0].textContent=t('Independent task — empty folder','独立任务：使用空目录');$('directory-mode').options[1].textContent=t('Existing project — preserve contents','已有项目：使用现有目录');
  $('task-help').textContent=t('Choose an existing folder or create one inside the system picker. Existing project mode preserves all contents. Selection does not start a model. Existing conversations reuse their confirmed folder.','可以选择已有文件夹，也可以在系统选择器中新建。已有项目模式保留全部内容。选择目录不会启动模型；已有会话复用已确认目录。');
  $('mode').options[0].textContent=t('Steer','补充当前 · Steer');$('mode').options[1].textContent=t('Queue','排队 · Queue');
  $('mode').title=t('Steer adds to the same active turn. Queue waits until it ends.','Steer 补充当前轮；Queue 等当前轮结束后执行。');
  for(const [id,en,cn] of [['files','Files','成果文件'],['session-details-label','Conversation details','会话详情'],['artifact-title','Task files','任务文件'],['artifact-refresh','Refresh files','刷新文件'],['artifact-close','Close','关闭'],['artifact-view-close','Close','关闭']])$(id).textContent=t(en,cn);
  $('session-technical-label').textContent=t('Technical identifiers','技术标识');
  $('confirm-result').textContent=t('Confirm checked result','确认已检查的结果');
  updateControls();
 }
 function outcomeLabel(){
  const reports={blocked:t('Task BLOCKED · inspect the latest result','任务受阻 BLOCKED · 请查看最近结果'),failed:t('Task failed · inspect the latest result','任务失败 · 请查看最近结果'),partial:t('Task partly completed · inspect the latest result','任务部分完成 · 请查看最近结果'),reported_pass:t('Executor reports PASS · artifact acceptance not verified','执行器回报 PASS · 产物尚待验收'),unverified:t('Channel finished · business result not verified','通道已结束 · 业务结果尚未核验')};
  return reports[businessResult]||(transport==='interrupted'?t('Stopped · conversation saved','已停止 · 会话已保存'):transport==='failed'?t('Not completed · inspect the latest output','未完成 · 请查看最近输出'):'');
 }
 function updateControls(){
  const checked=!!resultReceipt.ownerResultConfirmed;
  $('result-confirmation').hidden=!resultReceipt.submissionID||transport!=='completed'||busy||uncertain;
  $('confirm-result').hidden=checked;
  $('result-confirmation-note').textContent=checked?t('Your check is recorded for this result. The executor report is preserved.','已记录你对本次结果的确认，执行器原回报保留。'):t('Optional, after you have checked the result. Does not start another run.','检查结果后可选确认，不会开始新的执行。');
  const available=id=>catalog.some(x=>x.model===$(id).value&&!x.hidden);
  $('send').disabled=!connected||!selected||!historyReady||!controllable||uncertain||submitting||(awaitingTurn&&$('mode').value==='steer')||!available('model')||(!$('draft').value.trim()&&!$('attachments').children.length);
  $('threads').disabled=busy||submitting;$('model').disabled=false;$('connect').hidden=connected;$('connect').disabled=busy;$('refresh').disabled=busy||submitting;$('reconnect').hidden=!uncertain;$('stop').hidden=!busy||uncertain||awaitingTurn;$('stop').disabled=stopRequested;$('stop').textContent=stopRequested?t('Stopping…','正在停止…'):t('Stop','停止');$('return').hidden=!resultAvailable;
  $('draft').disabled=false;$('workspace').hidden=!selected;$('files').hidden=!selected||!controllable;$('session-details').hidden=!selected;$('new-task').disabled=!connected;
  $('next-turn').hidden=!busy;$('next-turn').textContent=t('Model and reasoning changes apply to the next turn. Steer keeps this turn’s settings.','模型和推理档位变更在下一轮生效；Steer 保持当前轮设置。');
  $('status').textContent=stopRequested?t('Stop requested · waiting for the actual turn to end','已请求停止 · 等待当前轮实际结束'):waitingRequests?t('Waiting for your decision','等待你的决定'):answeringRequests?t('Response sent · waiting for service confirmation','回答已发送 · 等待服务确认'):uncertain?t('Delivery needs verification · input retained','送达状态待核验 · 输入已保留'):awaitingTurn?t('Input accepted · waiting for the actual turn to start','输入已接收 · 等待实际轮次开始'):busy?t('Codex is working · you can keep typing','Codex 正在执行 · 可以继续输入'):selected&&!controllable?t('History only · control is not shared with the official App. Create an independent task to work here.','仅查看历史 · 未取得官方 App 会话控制权。可新建独立任务在此执行。'):outcomeLabel()?outcomeLabel():selected?(controlVerified?t('Folder-bound task · execution controlled by this connection','目录已绑定 · 本连接控制执行'):t('Folder confirmed · control will be verified before sending','目录已确认 · 发送前核验执行控制权')):'';
  $('task-busy').hidden=!busy;$('task-busy').textContent=t('You can prepare this folder now. Confirm after the current task finishes; it will not be interrupted.','可以先准备目录，当前任务完成后再确认；不会中断当前执行。');
  $('confirm-folder').disabled=!folderToken||busy||!connected||!available('task-model');
  $('confirm-handoff').disabled=!connected||!controllable||uncertain||submitting||!available('model');
  $('confirm-handoff').textContent=queuePaused?t('Save to paused queue','保存到已暂停队列'):busy?t('Queue after this task','加入后续队列'):t('Send and start','交付并开始');
  $('attach').disabled=!selected;
  $('send').title=busy?($('mode').value==='queue'?t('Queue after this turn','排队，当前轮结束后执行'):t('Steer this turn','补充当前轮')):t('Send','发送');
 }
 function resizeDraft(){const field=$('draft');field.style.height='auto';field.style.height=Math.min(180,Math.max(48,field.scrollHeight))+'px';}
 function updateScroll(){const log=$('timeline');$('latest').hidden=log.scrollHeight-log.scrollTop-log.clientHeight<100;}
 function artifactCards(rows){return rows.map(x=>'<article class="file-card"><strong>'+esc(x.path)+'</strong><small>'+esc(x.bytes)+' bytes</small>'+fileButtons(x.path)+'</article>').join('');}
 function rememberThread(row){
  if(!row?.id)return;
  const saved={...(threadRecords.get(row.id)||{}),id:row.id};
  for(const key of ['name','cwd','preview'])if(typeof row[key]==='string'&&row[key].trim())saved[key]=row[key];
  threadRecords.set(row.id,saved);
 }
 function threadLabel(id){
  const row=threadRecords.get(id)||{};
  const title=row.name||String(row.cwd||'').split('/').filter(Boolean).pop()||row.preview||t('Conversation','会话');
  return title.replace(/\s+/g,' ').slice(0,100);
 }
 function selectThreadOption(id){
  let option=Array.from($('threads').options).find(x=>x.value===id);
  if(!option){option=new Option('',id);$('threads').add(option);}
  option.textContent=threadLabel(id);$('threads').value=id;
 }
 function sessionFacts(p){
  const entries=[
   [t('Folder','工作目录'),p.cwd||actualCwd||t('Not loaded','尚未加载')],
   [t('Current model','当前模型'),p.actualModel||actualModel||t('Not loaded','尚未加载')],
   [t('Next turn','下一轮'),[p.nextModel,p.nextEffort].filter(Boolean).join(' · ')||t('Keep conversation settings','沿用会话设置')],
   [t('Execution control','执行控制'),p.controlVerified?t('Verified for this connection','本连接已核验'):p.controllable?t('Verified before sending','发送前核验'):t('History only','仅查看历史')]
  ];
  $('session-facts').replaceChildren();
  for(const [label,value] of entries){const term=document.createElement('dt'),definition=document.createElement('dd');term.textContent=label;definition.textContent=value;$('session-facts').append(term,definition);}
  $('session-identity').textContent=JSON.stringify({thread:p.threadId,turn:p.turnId||null,cwd:p.cwd||actualCwd,model:p.actualModel||actualModel,nextModel:p.nextModel,nextEffort:p.nextEffort,permission:p.permission,controlVerified:!!p.controlVerified},null,2);
 }
 function fillModels(id, preferred=''){
  const node=$(id), old=preferred||node.value;node.replaceChildren();
  for(const row of catalog.filter(x=>!x.hidden))node.add(new Option(row.displayName||row.model,row.model));
  if(Array.from(node.options).some(x=>x.value===old))node.value=old;
  else if(old){const missing=new Option(old+t(' · unavailable',' · 暂不可用'),old);missing.disabled=true;node.add(missing);node.value=old;}
  else node.value=(catalog.find(x=>x.isDefault&&!x.hidden)||catalog.find(x=>!x.hidden))?.model||'';
  fillEfforts(id==='model'?'effort':'task-effort',node.value);
 }
 function fillEfforts(id,model,preferred=''){
  const node=$(id),old=preferred||node.value,row=catalog.find(x=>x.model===model);node.replaceChildren();
  for(const option of row?.supportedReasoningEfforts||[])node.add(new Option(option.reasoningEffort,option.reasoningEffort));
  if(preferred&&!Array.from(node.options).some(x=>x.value===preferred)){const missing=new Option(preferred+t(' · unavailable',' · 暂不可用'),preferred);missing.disabled=true;node.add(missing);node.value=preferred;}
  else node.value=Array.from(node.options).some(x=>x.value===old)?old:row?.defaultReasoningEffort||'';
 }
 function inputSettings(){return {model:$('model').value,effort:$('effort').value};}
 const queueDrafts=new Map();
 function attachmentCoverage(value){
  if(!value)return t('Inline content','内联内容');
  const [kind,count]=value.split(':');
  const labels={text_full:t('Complete decoded text','完整解码文本'),image_native:t('Native image input','原生图片输入'),pdf_text:t('Text pages (no OCR/images)','文字页（不含 OCR/图片）'),docx_body_tables_text:t('Body and table text; no images/layout','正文与表格文字，不含图片/版式'),xlsx_cells_cached_formula_text:t('Sheets: cells/cached values/formula text; no charts','工作表：单元格/缓存值/公式文字，不含图表'),pptx_slide_text:t('Slide text; no images/notes','幻灯片文字，不含图片/备注')};return (labels[kind]||kind)+(count?' · '+count:'');
 }
 function renderQueue(p){
  queuePaused=!!p.paused&&!!(p.items||[]).length;
  $('queue-panel').hidden=!(p.items||[]).length;$('queue-items').replaceChildren();
  $('queue-paused').hidden=!p.paused;$('queue-paused').textContent=t('Automatic dispatch is paused after a failure, restart or uncertain delivery. Review before continuing.','失败、重启或送达不明后已暂停自动派发。核对后再继续。');
  $('resume-queue').hidden=!p.paused||uncertain||busy;$('inspect-delivery').hidden=!uncertain;
  const states={queued:t('Waiting','待派发'),preparing:t('Checking destination','核对目标'),sending:t('Sending','发送中'),accepted:t('Accepted; waiting for start','已接收，等待开始'),running:t('Running','运行中'),cancelled:t('Cancelled','已取消'),unknown:t('Receipt unknown','送达待核验'),rejected:t('Not delivered','未送达')};
  for(const item of p.items||[]){
   const row=document.createElement('section');row.className='queue-row';const text=document.createElement('p');text.textContent=item.text;row.append(text);
   const meta=document.createElement('small');meta.textContent=[states[item.state]||item.state,item.model,item.effort,...(item.attachments||[])].filter(Boolean).join(' · ');row.append(meta);
   if(item.error){const error=document.createElement('p');error.textContent=item.error;row.append(error);}
   if(item.recoverable){const resume=document.createElement('button');resume.textContent=t('Verify and start saved input','核验并启动已保存输入');resume.disabled=busy||submitting;resume.onclick=()=>post('startSavedQueue',{id:item.id});row.append(resume);}
   if(item.state==='queued'){
    const actions=document.createElement('div');actions.className='actions';
    if(item.editable){const edit=document.createElement('button');edit.textContent=t('Edit','编辑');edit.onclick=()=>{const field=document.createElement('textarea');field.value=queueDrafts.get(item.id)??item.text;field.oninput=()=>queueDrafts.set(item.id,field.value);text.replaceWith(field);edit.textContent=t('Save changes','保存修改');edit.onclick=()=>post('editQueue',{id:item.id,text:field.value});};actions.append(edit);if(queueDrafts.has(item.id))edit.click();}
    const remove=document.createElement('button');remove.textContent=t('Delete queued input','删除待发消息');remove.onclick=()=>post('deleteQueue',{id:item.id});actions.append(remove);row.append(actions);
   }
   $('queue-items').append(row);
  }
  updateControls();
 }
 async function acceptFiles(files){
  const target=selected;
  for(const file of files){
   if(file.size>8000000){showNotice(t('Attachment exceeds 8 MB.','附件超过 8 MB。'));continue;}
   try{const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});post('attachment',{threadId:target,name:file.name||'pasted-image.png',mime:file.type,base64:String(data).split(',')[1]});}
   catch{showNotice(t('This attachment could not be read.','无法读取此附件。'));}
  }
 }
 const stateLabel=value=>({inProgress:t('In progress','进行中'),completed:t('Finished','已结束'),failed:t('Failed','失败'),declined:t('Declined','已拒绝'),interrupted:t('Stopped','已停止'),pending:t('Waiting','等待中'),in_progress:t('In progress','进行中')})[value]||value||'';
 const fileButtons=path=>path?'<span class="file-actions">'+(/\.html?$/i.test(path)?'<button class="primary-file" data-file="'+esc(path)+'" data-operation="browser">'+t('Open webpage','打开网页')+'</button>':'')+'<button data-file="'+esc(path)+'" data-operation="view">'+t('View file','查看文件')+'</button><button data-file="'+esc(path)+'" data-operation="save">'+t('Save as…','另存为…')+'</button><button data-file="'+esc(path)+'" data-operation="reveal">'+t('Show in Finder','在 Finder 显示')+'</button></span>':'';
 const diffMarkup=text=>String(text||'').split('\n').map(line=>'<span class="diff-line '+(line.startsWith('+')&&!line.startsWith('+++')?'diff-add':line.startsWith('-')&&!line.startsWith('---')?'diff-delete':'')+'">'+esc(line)+'</span>').join('');
 // Only an explicit machine-style receipt is summarized. Every original byte
 // stays available; failure/limitations are never replaced by a success claim.
 function replyMarkup(text){
  const fields=[...String(text||'').matchAll(/^([A-Z][A-Z0-9_]{2,}):\s*([^\n]*)([\s\S]*?)(?=^[A-Z][A-Z0-9_]{2,}:|(?![\s\S]))/gm)];
  const names={RESULT:t('Reported result','执行器报告结果'),BUSINESS_RESULT:t('Reported result','执行器报告结果'),SUMMARY:t('Summary','说明'),DELIVERABLE_ABSOLUTE_PATH:t('File','文件'),REPORTED_FILE:t('File','文件'),FILES_CREATED_OR_MODIFIED:t('Changes','文件改动'),KNOWN_LIMITATIONS:t('Remaining checks','尚未完成的检查'),REMAINING_GAP:t('Remaining work','尚未完成'),REAL_BROWSER:t('Browser check','浏览器检查'),REAL_REFRESH_PERSISTENCE:t('Refresh check','刷新保留检查')};
  const visible=fields.filter(f=>names[f[1]]);
  if(fields.length<3||!visible.length||String(text).slice(0,fields[0].index).trim())return markdown(text);
  return '<section class="receipt"><dl>'+visible.map(f=>'<dt>'+esc(names[f[1]])+'</dt><dd>'+markdown(f[2]+f[3])+'</dd>').join('')+'</dl><details><summary>'+t('Full execution receipt','完整执行回执')+'</summary><pre>'+esc(text)+'</pre></details></section>';
 }
 function renderItem(item,prepend=false){
  if(!item?.id)return;items.set(item.id,item);
  let node=document.getElementById('item-'+item.id), fresh=!node;
  if(fresh){node=document.createElement('article');node.id='item-'+item.id;node.className='message';}
  node.querySelectorAll('details').forEach((d,i)=>detailState.set(selected+':'+item.id+':'+i,d.open));
  node.className='message';node.dataset.status=item.status||'';
  const meta=item.status?'<span class="activity-status">'+esc(stateLabel(item.status))+'</span>':'';
  if(item.type==='userMessage'){
   node.className='message user';node.replaceChildren();
   for(const part of item.content||[]){
    if(part.type==='text'){
     if(part.text?.startsWith('TWOS controller-verified execution context /')){
      const details=document.createElement('details'),label=document.createElement('summary'),pre=document.createElement('pre');label.textContent=t('Verified task folder and scope','已核验的任务目录与范围');pre.textContent=part.text;details.append(label,pre);node.append(details);
     }else if(/^(?:Local parsing coverage: [^\n]*\n)?Text attachment supplied inline: /.test(part.text||'')){
      const details=document.createElement('details'),label=document.createElement('summary'),pre=document.createElement('pre');
      label.textContent=t('Attachment · ','附件 · ')+(part.text.match(/Text attachment supplied inline: ([^\n]+)/)?.[1]||'');
      pre.textContent=part.text;details.append(label,pre);node.append(details);
     }else if(part.text?.startsWith('Image attachment supplied next: ')){
      const details=document.createElement('details'),label=document.createElement('summary'),pre=document.createElement('pre');label.textContent=t('Image · ','图片 · ')+(part.text.split('\n')[0].slice('Image attachment supplied next: '.length));pre.textContent=part.text;details.append(label,pre);node.append(details);
     }else{const text=document.createElement('div');text.textContent=part.text;node.append(text);}
    }else if(part.type==='image'&&/^data:image\/(png|jpeg);base64,/.test(part.url||'')){
     const img=document.createElement('img');img.src=part.url;img.alt=t('Sent image','已发送图片');img.className='sent-image';node.append(img);
    }else if(part.type==='image'||part.type==='localImage'){
     const text=document.createElement('small');text.textContent=t('Image attachment recorded in this message','此消息包含图片附件');node.append(text);
    }
   }
  }else if(item.type==='agentMessage'){node.innerHTML=replyMarkup(item.text||'');}
  else if(item.type==='reasoning'){
   const text=summaryText(item.summary);if(!text)return;
   node.classList.add('activity');node.innerHTML='<details><summary><span class="activity-title">'+t('Thinking summary','思考摘要')+'</span></summary>'+markdown(text)+'</details>';
  }else if(item.type==='commandExecution'){
   const command=item.command||t('Command','命令'),brief=command.split('\n')[0];
   node.classList.add('activity');node.innerHTML='<details><summary><span class="activity-title">'+esc(brief.length>90?brief.slice(0,90)+'…':brief)+'</span>'+meta+'</summary><pre>'+esc(command)+'</pre>'+(item.cwd?'<p class="command-cwd">cwd: '+esc(item.cwd)+'</p>':'')+'<pre>'+esc(item.aggregatedOutput||'')+'</pre>'+(item.exitCode==null?'':'<p>'+t('Exit code: ','退出码：')+esc(item.exitCode)+'</p>')+'</details>';
  }else if(item.type==='fileChange'){
   node.classList.add('activity');node.innerHTML='<details><summary><span class="activity-title">'+t('File changes / diff','文件改动 / 差异')+'</span>'+meta+'</summary>'+(item.changes||[]).map(c=>'<p>'+esc(c.path||t('Turn diff','本轮差异'))+'</p>'+fileButtons(c.path)+'<pre class="diff">'+diffMarkup(c.diff)+'</pre>').join('')+(item.aggregatedOutput?'<pre>'+esc(item.aggregatedOutput)+'</pre>':'')+'</details>';
  }else if(item.type==='plan'){
   node.innerHTML=item.steps?'<div class="plan">'+markdown(item.explanation||'')+'<ol>'+item.steps.map(x=>'<li><span>'+esc(stateLabel(x.status))+'</span> '+esc(x.step)+'</li>').join('')+'</ol></div>':markdown(item.text||'');
  }else if(['mcpToolCall','dynamicToolCall','functionCallOutput','webSearch','imageView','imageGeneration','collabAgentToolCall','subAgentActivity','contextCompaction','enteredReviewMode','exitedReviewMode','sleep'].includes(item.type)){
   const titles={mcpToolCall:t('Tool','工具'),dynamicToolCall:t('Tool','工具'),functionCallOutput:t('Tool result','工具结果'),webSearch:t('Web search','网页搜索'),imageView:t('View image','查看图片'),imageGeneration:t('Image generation','生成图片'),collabAgentToolCall:t('Agent activity','代理活动'),subAgentActivity:t('Agent activity','代理活动'),contextCompaction:t('Context compacted','上下文整理'),enteredReviewMode:t('Review started','开始复核'),exitedReviewMode:t('Review ended','复核结束'),sleep:t('Waiting','等待')};
   const title=[titles[item.type],item.server,item.tool||item.name||item.query].filter(Boolean).join(' · ');
   const description=item.progress||item.error?.message||(typeof item.output==='string'?item.output:'');
   const safe={...item};delete safe.id;delete safe.type;
   node.classList.add('activity');node.innerHTML='<details><summary><span class="activity-title">'+esc(title)+'</span>'+meta+'</summary>'+(description?'<p>'+esc(description)+'</p>':'')+fileButtons(item.path||item.savedPath)+'<details><summary>'+t('Tool details','工具详情')+'</summary><pre>'+esc(JSON.stringify(safe,null,2))+'</pre></details></details>';
  }else return;
  if(['userMessage','agentMessage'].includes(item.type)){
   const actions=document.createElement('div');actions.className='message-actions';const copy=document.createElement('button');copy.textContent=t('Copy','复制');copy.onclick=()=>post('copy',{text:item.type==='agentMessage'?item.text:(item.content||[]).filter(x=>x.type==='text').map(x=>x.text).join('\n\n')});actions.append(copy);node.append(actions);
  }
  node.querySelectorAll('details').forEach((d,i)=>{const key=selected+':'+item.id+':'+i;d.open=detailState.has(key)?detailState.get(key):(item.type==='reasoning'&&busy);d.ontoggle=()=>detailState.set(key,d.open);});
  if(fresh){$('empty')?.remove();prepend?$('timeline').prepend(node):$('timeline').append(node);}
 }
 const approvalRecords=new Map();
 function approval(p){
  approvalRecords.set(p.key,p);
  document.querySelector('.approval[data-key="'+CSS.escape(p.key)+'"]')?.remove();
  const box=document.createElement('section');box.className='approval';box.dataset.key=p.key;
  const params=p.params||{};
  const scope=document.createElement('details');scope.innerHTML='<summary>'+t('Request scope','请求范围')+'</summary><pre>'+esc(JSON.stringify({thread:params.threadId,turn:params.turnId,item:params.itemId,request:p.key,cwd:params.cwd},null,2))+'</pre>';
  if(p.method==='item/tool/requestUserInput'){
   for(const q of params.questions||[]){
    const field=document.createElement('fieldset');field.dataset.question=q.id;const legend=document.createElement('legend');legend.textContent=q.question||q.header||'';field.append(legend);
    for(const option of q.options||[]){const label=document.createElement('label'),radio=document.createElement('input');radio.type='radio';radio.name=p.key+':'+q.id;radio.value=option.label;label.append(radio,document.createTextNode(option.label+(option.description?' — '+option.description:'')));field.append(label);}
    const input=document.createElement(q.isSecret?'input':'textarea');if(q.isSecret)input.type='password';input.setAttribute('aria-label',t('Your answer or comment','你的回答或补充'));input.placeholder=t('Answer or add a comment','填写回答或补充说明');field.append(input);box.append(field);
   }
   const send=document.createElement('button');send.textContent=t('Reply','回复');send.onclick=()=>{const answers={};let valid=true;box.querySelectorAll('[data-question]').forEach(field=>{const chosen=field.querySelector('input[type=radio]:checked')?.value;const free=field.querySelector('textarea,input[type=password]').value.trim();answers[field.dataset.question]=[chosen,free].filter(Boolean);if(!answers[field.dataset.question].length)valid=false;});if(valid)post('answer',{key:p.key,answers});};box.append(send);
  }else{
   const reason=document.createElement('p');reason.textContent=params.reason||t('Codex requests your decision.','Codex 请求你的决定。');box.append(reason);
   if(p.scopeExpansion){const boundary=document.createElement('p');boundary.textContent=t('This request expands the task permissions. This workbench keeps the confirmed folder and network boundary.','此请求扩大任务权限；工作台保持已确认目录和网络边界。');box.append(boundary);}
   const command=document.createElement('pre');command.textContent=params.command||params.grantRoot||JSON.stringify(params.permissions||params.networkApprovalContext||{},null,2);box.append(command);
   const decisions=p.method==='item/permissions/requestApproval'?['decline']:(p.decisions||['accept','decline','cancel']);
   for(const decision of decisions){const button=document.createElement('button');button.textContent=({accept:t('Approve once','允许本次'),decline:t('Reject','拒绝'),cancel:t('Reject and stop','拒绝并停止')})[decision];button.onclick=()=>post('answer',{key:p.key,decision,accept:decision==='accept'});box.append(button);}
  }
  box.append(scope);const waiting=document.createElement('p');waiting.className='approval-wait';waiting.hidden=!p.answering;waiting.textContent=t('Response sent · waiting for service confirmation','回答已发送 · 等待服务确认');box.append(waiting);
  if(p.answering)box.querySelectorAll('button,input,textarea').forEach(x=>x.disabled=true);
  $('approvals').append(box);
 }
 window.twosReceive=({kind,payload:p})=>{
  if(kind==='nyra'){nyraState=p;labels();return;}
  if(kind==='telemetry'){window.twosTelemetry.receive(p);return;}
  if(kind==='attachmentParsing'){$('attachment-parsing').hidden=!p.parsing;$('attachment-parsing').textContent=t('Reading locally, not sent: ','正在本机读取，尚未发送：')+p.name;return;}
  if(kind==='locale'){
   const old=zh;zh=p.zh;window.twosTelemetry.language(zh);$('language').value=zh?'zh-CN':'en-US';document.documentElement.lang=zh?'zh-CN':'en-US';labels();
   // Translate only TWOS controls, never message text, paths or filenames.
   const localize=text=>{for(const [key,v] of Object.entries(p.catalog||{}))if(text===key||text===v[old?'zh-CN':'en-US'])return v[zh?'zh-CN':'en-US']||key;return text;};
   $('notice-text').textContent=localize($('notice-text').textContent);
   for(const [key,record] of approvalRecords){
    const prior=document.querySelector('.approval[data-key="'+CSS.escape(key)+'"]');if(!prior)continue;
    const inputs=[...prior.querySelectorAll('input,textarea')].map(x=>({value:x.value,checked:x.checked}));
    approval(record);const next=document.querySelector('.approval[data-key="'+CSS.escape(key)+'"]');
    next.querySelectorAll('input,textarea').forEach((x,i)=>{if(inputs[i]){x.value=inputs[i].value;x.checked=inputs[i].checked;}});
   }
   for(const item of items.values())renderItem(item);

   for(const button of document.querySelectorAll('[data-file]'))button.textContent=({view:t('View file','查看文件'),save:t('Save as…','另存为…'),reveal:t('Show in Finder','在 Finder 显示'),browser:t('Open webpage','打开网页')})[button.dataset.operation];
  }
  else if(kind==='directoryCleared'){folderToken='';$('folder-path').textContent='';$('folder-scope').textContent='';updateControls();}
  else if(kind==='control'){window.twosTelemetry?.selectThread(p.threadId||'');connected=p.connected;busy=p.busy;awaitingTurn=!!p.awaitingTurn;stopRequested=!!p.stopRequested;waitingRequests=p.waitingRequests||0;answeringRequests=p.answeringRequests||0;actualCwd=p.cwd||actualCwd;actualModel=p.actualModel||actualModel;activeTurn=p.turnId||'';sessionFacts(p);uncertain=!!p.uncertain;historyReady=!!p.historyReady;desktop=p.desktopRunning;selected=p.threadId||'';controllable=!!p.controllable;controlVerified=!!p.controlVerified;submitting=!!p.submitting;if(p.mode)$('mode').value=p.mode;if(p.nextModel){desiredModel=p.nextModel;desiredEffort=p.nextEffort||'';if(catalog.length){fillModels('model',desiredModel);fillEfforts('effort',desiredModel,desiredEffort);}}updateControls();}
  else if(kind==='newTask'){folderToken='';$('folder-path').textContent='';$('folder-scope').textContent='';$('task-panel').hidden=false;$('task-panel').scrollIntoView({block:'nearest'});updateControls();}
  else if(kind==='directory'){folderToken=p.token;$('folder-path').textContent=p.path;$('folder-scope').textContent=p.scope;$('task-panel').hidden=false;updateControls();}
  else if(kind==='directoryConfirmed'){folderToken='';$('task-panel').hidden=true;$('notice').hidden=true;}
  else if(kind==='handoff'){
   handoffHash=p.hash;$('handoff-panel').hidden=false;$('handoff-preview').textContent=p.text;
   $('handoff-target').textContent=p.canControl?[p.cwd,p.model,p.effort,...(p.attachments||[])].filter(Boolean).join(' · '):t('Choose a task folder and model below.','请在此选择任务目录和模型。');
   $('handoff-scope').textContent=t('These instructions, selected attachments and the controller-verified task folder context will be sent. Folder permissions and tool approvals remain in force.','发送这份完整指令、你选择的附件和控制端核验后的任务目录上下文。目录边界和工具批准保持有效。');
   if(!p.canControl)$('task-panel').hidden=false;updateControls();
  }
  else if(kind==='handoffReceipt'){$('handoff-panel').hidden=true;}
  else if(kind==='queue')renderQueue(p);
  else if(kind==='attachments'){
   $('attachments').replaceChildren();
   for(const item of p.items||[]){const box=document.createElement('div');box.className='attachment';
    if(item.preview){const img=document.createElement('img');img.src=item.preview;img.alt=item.name;box.append(img);}
    const name=document.createElement('span');name.textContent=item.name;box.append(name);const coverage=document.createElement('small');coverage.textContent=attachmentCoverage(item.coverage)+' · '+item.bytes+t(' bytes · attached, not sent',' 字节 · 已附加，尚未发送')+(item.hash?' · SHA-256 '+item.hash.slice(0,12):'');box.append(coverage);const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',t('Remove ','移除 ')+item.name);remove.onclick=()=>post('removeAttachment',{id:item.id});box.append(remove);$('attachments').append(box);
   }updateControls();
  }
  else if(kind==='notice')showNotice(p.text+(p.code?' ('+p.code+')':''),p.detail||'');
  else if(kind==='result'){resultReceipt=p;resultAvailable=!!p.available;businessResult=p.businessResult||'';transport=p.transport||'';updateControls();}
  else if(kind==='clearApprovals'){$('approvals').replaceChildren();waitingRequests=0;answeringRequests=0;updateControls();}
  else if(kind==='displaySnapshot'){for(const item of p.items||[])renderItem(item);}
  else if(kind==='approvalPending'){if(approvalRecords.has(p.key))approvalRecords.get(p.key).answering=true;const box=document.querySelector('.approval[data-key="'+CSS.escape(p.key)+'"]');if(box){box.querySelectorAll('button,input,textarea').forEach(x=>x.disabled=true);box.querySelector('.approval-wait').hidden=false;}}
  else if(kind==='artifacts'){
   if(p.threadId!==selected)return;const rows=p.items||[];
   $('artifact-help').textContent=rows.length?t('Files in the confirmed task folder. Opening is not a functional test.','已确认任务目录中的文件。打开成功不代表功能已验收。'):t('No supported files in the folder yet.','目录内暂未发现支持的文件。');$('artifact-items').innerHTML=artifactCards(rows);
   if(p.automatic){$('result-files').hidden=!rows.length;$('result-files').innerHTML='<div class="result-file-heading">'+t('Workspace files','工作目录文件')+' · '+rows.length+'</div>'+artifactCards(rows.slice(0,3))+(rows.length>3?'<button data-more-files>'+t('All files','全部文件')+'</button>':'');}
   else $('artifact-panel').hidden=false;
  }
  else if(kind==='artifactContent'){if(p.threadId!==selected)return;$('artifact-path').textContent=p.path;$('artifact-text').textContent=p.text||'';$('artifact-text').hidden=!!p.image;$('artifact-image').hidden=!p.image;$('artifact-image').src=p.image||'';if(!$('artifact-view').open)$('artifact-view').showModal();}
  else if(kind==='artifactOpened'){showNotice(p.opened?t('Opened in Safari. Functionality, viewport and refresh persistence still need actual checks.','已在 Safari 打开。功能、手机宽度和刷新保留仍需实际检查。'):t('Safari did not confirm opening the file.','Safari 未确认打开该文件。'),p.error||'');}
  else if(kind==='artifactSaved'){if(p.threadId!==selected)return;showNotice(t('Copy saved. The original file is unchanged.','副本已保存，原文件保持不变。')+'\n'+p.destination);}
  else if(kind==='threads'){
   const prior=$('threads').value; $('threads').replaceChildren(new Option(t('Choose existing conversation','选择已有会话'),''));
   for(const row of p.items||[]){rememberThread(row);$('threads').add(new Option(threadLabel(row.id),row.id));}
   const target=selected||prior||savedThread;
   if(target)selectThreadOption(target);$('more-threads').hidden=!p.more;
   if(!selected&&savedThread&&$('threads').value===savedThread){post('select',{id:savedThread});savedThread='';}
  }else if(kind==='models'){
   catalog=p.items||[];fillModels('model',desiredModel);fillEfforts('effort',$('model').value,desiredEffort);fillModels('task-model');updateControls();
  }else if(kind==='thread'){
   if(selected!==p.thread.id){$('session-details').open=false;$('session-technical').open=false;}
   window.twosTelemetry?.selectThread(p.thread.id);selected=p.thread.id;rememberThread(p.thread);selectThreadOption(selected);actualCwd=p.thread.cwd||'';actualModel=p.thread.model||'';$('cwd').textContent=actualCwd;$('cwd').title=actualCwd;if(catalog.length){fillModels('model',p.thread.model||'');fillEfforts('effort',$('model').value,p.thread.reasoningEffort||'');}
   $('timeline').replaceChildren();$('approvals').replaceChildren();$('artifact-panel').hidden=true;$('result-files').hidden=true;$('result-files').replaceChildren();$('latest').hidden=true;if($('artifact-view').open)$('artifact-view').close();items.clear();resultReceipt={};lastFinal='';businessResult='';transport='';resultAvailable=false;$('return').hidden=true;updateControls();
  }else if(kind==='history'){
   const turns=[...(p.turns||[])].reverse();const prior=[];
   if(p.older){prior.push(...$('timeline').children);$('timeline').replaceChildren();}
   for(const turn of turns)for(const item of turn.items||[])renderItem(item);
   if(p.older)for(const item of prior){document.getElementById(item.id)?.remove();$('timeline').append(item);}
   else $('timeline').scrollTop=$('timeline').scrollHeight;
   $('more').hidden=!p.more;
  }else if(kind==='draft'){
   $('draft').value=p.text||'';source=p.source||'';savedThread=p.savedThread||savedThread;$('source').hidden=!source;$('source').textContent=source?t('From: ','来自：')+source:'';resizeDraft();updateControls();
  }else if(kind==='sent'){
   if($('draft').value===p.text)$('draft').value='';if(busy){businessResult='';transport='';$('notice').hidden=true;}resizeDraft();updateControls();
  }else if(kind==='approval')approval(p);
  else if(kind==='answered')document.querySelector('.approval[data-key="'+CSS.escape(p.key)+'"]')?.remove();
  else if(kind==='summary')renderItem({id:p.id,type:'reasoning',summary:p.summary});
  else if(kind==='turnCompleted'){
   if(retryNotice){$('notice').hidden=true;retryNotice=false;}
   $('approvals').replaceChildren();waitingRequests=0;answeringRequests=0;stopRequested=false;transport=p.status;updateControls();
   if(p.status==='completed'&&!['blocked','failed','partial'].includes(businessResult))$('notice').hidden=true;
   if(p.error)showNotice(t('The response did not finish.','回复未能完成。'),p.error.message||String(p.error));
  }else if(kind==='event'){
   const e=p.params||{};
   if(retryNotice&&p.method.startsWith('item/')){$('notice').hidden=true;retryNotice=false;}
   const nearEnd=$('timeline').scrollHeight-$('timeline').scrollTop-$('timeline').clientHeight<100;
   if(p.method==='item/started'||p.method==='item/completed')renderItem(e.item);
   else if(p.method==='item/agentMessage/delta'){
    const item=items.get(e.itemId)||{id:e.itemId,type:'agentMessage',text:''};item.text+=(e.delta||'');renderItem(item);
   }else if(p.method==='item/commandExecution/outputDelta'){
    const item=items.get(e.itemId)||{id:e.itemId,type:'commandExecution',command:''};item.aggregatedOutput=(item.aggregatedOutput||'')+(e.delta||'');renderItem(item);
   }else if(p.method==='item/reasoning/summaryTextDelta'){
    const item=items.get(e.itemId)||{id:e.itemId,type:'reasoning',summary:[]};const i=e.summaryIndex||0;item.summary=Array.isArray(item.summary)?item.summary:[];while(item.summary.length<=i)item.summary.push('');item.summary[i]=(typeof item.summary[i]==='string'?item.summary[i]:item.summary[i]?.text||'')+(e.delta||'');renderItem(item);
   }else if(p.method==='turn/plan/updated'){
    renderItem({id:'plan-'+e.turnId,type:'plan',steps:e.plan||[],explanation:e.explanation||''});
   }else if(p.method==='turn/diff/updated')renderItem({id:'diff-'+e.turnId,type:'fileChange',changes:[{path:'',diff:e.diff||''}]});
   else if(p.method==='item/fileChange/outputDelta'){const item=items.get(e.itemId)||{id:e.itemId,type:'fileChange',changes:[]};item.aggregatedOutput=(item.aggregatedOutput||'')+(e.delta||'');renderItem(item);}
   else if(p.method==='item/mcpToolCall/progress'){const item=items.get(e.itemId)||{id:e.itemId,type:'mcpToolCall'};item.progress=e.message;renderItem(item);}
   else if(p.method==='error'){showNotice(e.willRetry?t('Codex is reconnecting…','Codex 正在重新连接…'):t('Codex reported an error. This request was not restarted automatically.','Codex 返回了错误，本请求没有自动重新执行。'),e.error?.message||e.message||'');retryNotice=!!e.willRetry;}
   if(nearEnd)$('timeline').scrollTop=$('timeline').scrollHeight;updateScroll();
  }
 };
 $('pet-control').onclick=()=>{if(nyraState.available)post('nyra');const p=$('pet-info');p.hidden=!p.hidden;$('pet-control').setAttribute('aria-expanded',String(!p.hidden));};
 $('language').onchange=()=>post('language',{locale:$('language').value});
 $('connect').onclick=()=>post('connect');$('reconnect').onclick=()=>post('reconnect');$('more-threads').onclick=()=>post('moreThreads');$('refresh').onclick=()=>post('refresh');$('threads').onchange=()=>{clearTimeout(draftTimer);post('draft',{threadId:selected,text:$('draft').value});post('select',{id:$('threads').value});};
 $('workspace').onclick=()=>post('workspace');$('more').onclick=()=>post('more');$('return').onclick=()=>post('return');$('stop').onclick=()=>post('interrupt');
 $('draft').addEventListener('input',()=>{resizeDraft();updateControls();clearTimeout(draftTimer);draftTimer=setTimeout(()=>post('draft',{threadId:selected,text:$('draft').value}),180);});
 $('draft').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&!composing&&e.keyCode!==229&&performance.now()-compositionEndedAt>50){e.preventDefault();if(!$('send').disabled)$('composer').requestSubmit();}});
 $('composer').onsubmit=e=>{e.preventDefault();if($('send').disabled)return;clearTimeout(draftTimer);post('draft',{threadId:selected,text:$('draft').value});post('send',{threadId:selected,text:$('draft').value,...inputSettings(),mode:$('mode').value});};
 $('new-task').onclick=()=>post('newTask');$('handoff-new').onclick=()=>post('newTask');
 $('choose-folder').onclick=()=>post('chooseDirectory',{create:false,isolated:$('directory-mode').value==='isolated'});$('create-folder').onclick=()=>post('chooseDirectory',{create:true,isolated:$('directory-mode').value==='isolated'});
 $('directory-mode').onchange=()=>{post('directoryMode');folderToken='';$('folder-path').textContent='';$('folder-scope').textContent='';updateControls();};
 $('confirm-folder').onclick=()=>post('confirmDirectory',{token:folderToken,model:$('task-model').value,effort:$('task-effort').value});
 $('cancel-folder').onclick=()=>{post('cancelDirectory');folderToken='';$('task-panel').hidden=true;$('handoff-panel').hidden=true;};
 $('confirm-handoff').onclick=()=>post('confirmHandoff',{hash:handoffHash,...inputSettings()});$('cancel-handoff').onclick=()=>{post('cancelHandoff');$('handoff-panel').hidden=true;};
 $('mode').onchange=()=>{updateControls();post('mode',{mode:$('mode').value});};$('model').onchange=()=>{fillEfforts('effort',$('model').value);updateControls();post('model',inputSettings());};$('effort').onchange=()=>post('model',inputSettings());
 $('task-model').onchange=()=>{fillEfforts('task-effort',$('task-model').value);updateControls();};
 $('attach').onclick=()=>post('attach');$('resume-queue').onclick=()=>post('resumeQueue');$('inspect-delivery').onclick=()=>post('inspectDelivery');
 $('draft').addEventListener('compositionstart',()=>composing=true);$('draft').addEventListener('compositionend',()=>{composing=false;compositionEndedAt=performance.now();});
 $('composer').addEventListener('dragover',e=>{e.preventDefault();$('composer').classList.add('dragover');});$('composer').addEventListener('dragleave',()=>$('composer').classList.remove('dragover'));
 $('composer').addEventListener('drop',e=>{e.preventDefault();$('composer').classList.remove('dragover');acceptFiles([...e.dataTransfer.files]);});
 $('draft').addEventListener('paste',e=>{const files=[...e.clipboardData.items].filter(x=>x.kind==='file'&&x.type.startsWith('image/')).map(x=>x.getAsFile()).filter(Boolean);if(files.length){e.preventDefault();acceptFiles(files);}});
 $('confirm-result').onclick=()=>post('confirmResult',{threadId:selected,id:resultReceipt.submissionID,turn:resultReceipt.turnID,resultHash:resultReceipt.resultHash});
 $('files').onclick=$('artifact-refresh').onclick=()=>post('artifacts',{threadId:selected});$('artifact-close').onclick=()=>$('artifact-panel').hidden=true;$('artifact-view-close').onclick=()=>$('artifact-view').close();
 document.addEventListener('click',e=>{const button=e.target.closest('[data-file]');if(button)post('artifact',{threadId:selected,path:button.dataset.file,operation:button.dataset.operation});else if(e.target.closest('[data-more-files]'))post('artifacts',{threadId:selected});});
 $('notice-close').onclick=()=>$('notice').hidden=true;$('timeline').addEventListener('scroll',updateScroll);
 $('latest').onclick=()=>{$('timeline').scrollTop=$('timeline').scrollHeight;updateScroll();};
 labels();post('ready');
})();
