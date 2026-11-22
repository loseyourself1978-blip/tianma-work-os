'use strict';
const $ = id => document.getElementById(id);
const slots = ['Planner','Builder','Reviewer','Supervisor','Tester','Compliance'];
const faces = ['ada','kai','ren','mira','sol','lou'];
const duties = ['Planner','Builder','Supervisor','Reviewer','Tester','Acceptance checker','Compliance reviewer'];
const providers = {Codex:'OpenAI',ChatGPT:'OpenAI',Claude:'Anthropic',DeepSeek:'DeepSeek'};
let state = {}, room, tab='members', focusAttempt='', composing=false, mentions=false, edit=null;
let currentKey='', recipients=[], sending='', errorLocal='', feedStamp='', sideStamp='', formRoom='';
const expanded=new Set();
const tr=(en,zh)=>state.zh?zh:en;
const terms={
  draft:['New','新建'],running:['Running','执行中'],stopping:['Stopping…','正在停止…'],stopped:['Stopped','已停止'],
  paused:['Paused','已暂停'],blocked:['Needs attention','需要处理'],awaitingOwner:['Ready for your review','等待你验收'],
  completed:['Completed','已完成'],accepted:['Accepted','已接受'],changes:['Changes requested','已要求修改'],
  retainedDraft:['Draft · not sent','草稿 · 尚未发送'],sent:['Sent','已发送'],unsent:['Not sent','未送达'],intent:['Preparing','准备中'],unknown:['Delivery unconfirmed','送达待确认'],
  sending:['Sending','发送中'],queued:['Queued','队列中'],failed:['Failed','失败'],cancelled:['Cancelled','已取消'],
  rejected:['Rejected','已拒绝'],interrupted:['Interrupted','已中断'],Planner:['Planning','计划'],Builder:['Production','执行'],
  Supervisor:['Supervision','监督'],Reviewer:['Review','审查'],Tester:['Testing','测试'],
  'Acceptance checker':['Acceptance checks','验收检查'],'Compliance reviewer':['Compliance review','合规审查'],
  coordinate:['Planning','规划'],direct:['Direct reply','定向回复'],consult:['Consultation','协作'],build:['Production','制作'],
  review:['Independent review','独立审核'],strategy:['Reviewing the approach','调整方案'],
  approve:['Reviewed','已审核'],revise:['Changes requested','需要修改'],identityPending:['Model identity unconfirmed','模型身份待核实'],
  needs_evidence:['Evidence needed','等待证据'],decision:['Waiting for your reply','等待你回复'],
  identity:['The provider did not confirm the model used. Independent approval is pending.','提供方尚未确认实际模型，独立审核结论待核实。'],
  outputNeeded:['Choose where to save the files.','请选择成果保存位置。'],fileConflict:['The file changed or already belongs to someone else. Inspect it before continuing.','文件已变化或存在同名文件，请核对后再继续。'],
  changedDirectory:['The selected folder is unavailable or changed.','所选目录不可用或已变化。'],
  restart:['The app restarted. Check the existing dispatch to continue.','应用已重启，请核对已有派发以继续。'],
  unconfirmed:['Delivery is uncertain. Reconcile the original request.','送达情况待确认，请核对原请求。'],
  reviewerChat:['Open the member’s assigned conversation and reconcile.','请打开成员绑定的会话并核对。'],
  reviewerChanged:['The website model selection changed. Check the member settings.','网页所选模型已变化，请核对成员配置。'],
  reviewerDraft:['The website retained a draft. Check the original conversation before continuing.','网页保留了草稿，请在原会话核对后继续。'],
  codexUnavailable:['Local Codex is unavailable. Open the member connection to check it.','本机 Codex 不可用，请打开成员连接核对。'],
  alreadyQueued:['This message is already queued. Use the connection action below.','相同消息已在队列中，请使用连接操作继续。'],
  reviewerUnavailable:['Open the member’s website and check sign-in, model selection and availability.','请打开该成员的网页核对登录、模型选择和可用性。'],
  attachmentUnsupported:['This channel cannot read this attachment. Choose a supported file or another member.','当前通道无法读取该附件，请选择支持的文件或成员。'],
  tooLarge:['Choose up to eight files, 8 MB each and 12 MB total.','最多八个文件，每个不超过 8 MB，总计不超过 12 MB。'],
  invalidRoster:['Check member names, duties and independent reviewer assignment.','请核对成员姓名、职责和独立审核分配。'],
  contextTooLarge:['The selected evidence is too large to send intact. Narrow the task or attachments.','完整证据超过通道容量，请缩小任务或附件。'],
  wrongVersion:['The message, task or file version changed. Check the current view.','消息、任务或文件版本已变化，请核对当前内容。'],
  memberUnavailable:['The addressed member is unavailable. Update the recipients or team.','指定成员不可用，请更新收件人或团队。'],
  legacyUnconfirmed:['An earlier dispatch has no terminal receipt. Ask about its history or explicitly start new work.','旧操作缺少终态记录，可询问历史，或明确发起新的工作。'],
  roster:['Team update','团队调整'],confirmContinuation:['This task was stopped. Send an explicit request to resume or start new work.','该任务已停止，请明确说明继续或开始新工作。'],
  goal:['Goal','任务目标'],privateNote:['Private note','私人备注'],
  busy:['An operation is in progress.','操作正在进行。'],invalidInput:['Check the message or member configuration.','请检查输入或成员配置。'],
  archiveError:['One or more saved chats could not be loaded.','部分群聊未能读取。'],
  storage:['The chat could not be safely saved. Check the task storage.','无法安全保存群聊，请检查任务存储。'],
  unavailable:['The requested action is unavailable.','当前操作不可用。'],timeout:['The request timed out. Check its receipt.','请求超时，请核对回执。']
};
function label(key){const copy=terms[key]||connectionCopy[key];return copy ? tr(...copy) : key || '';}
function el(tag,txt,cls){const x=document.createElement(tag);if(txt!==undefined)x.textContent=txt;if(cls)x.className=cls;return x;}
function btn(text,act,cls){const b=el('button',text,cls);b.type='button';b.onclick=act;return b;}
function post(action,args={}){window.webkit.messageHandlers.teamChat.postMessage({action,id:room?.id||state.id,...args});}
function member(id){return room?.members.find(m=>m.role===id);}
function display(m){return m?.displayName || m?.role || '';}
function face(m){
  const img=el('img',undefined,'portrait'), src=faces[slots.indexOf(m?.role)];
  img.alt=display(m);img.src='avatars/'+(src||faces[0])+'.png';
  img.onerror=()=>{const fallback=el('span','♙','portrait fallback');fallback.setAttribute('aria-label',img.alt);img.replaceWith(fallback);};
  return img;
}
function row(...children){const r=el('div',undefined,'line');r.append(...children);return r;}
function actionLink(t,fn){return btn(t,fn,'inline');}
function chooseTab(t,a=''){tab=t;focusAttempt=a;edit=null;sideStamp='';$('inspector').classList.add('open');renderSide();}
function saveDraft(){if(!room||!currentKey||sending===currentKey)return;post('draft',{key:currentKey,text:$('message').value,recipients:[...recipients]});}
function updateSend(){$('message').readOnly=!!sending&&sending===currentKey;$('send').disabled=!state.writable||!room||room.processing||sending===currentKey||(!$('message').value.trim()&&!(room.draft.attachments||[]).length);}
function send(){
  if(composing||$('send').disabled)return;
  sending=currentKey;updateSend();mentions=false;paintMentions();
  post('send',{key:currentKey,text:$('message').value,recipients:[...recipients]});
}
function attachment(ref){return actionLink('▤ '+ref.name,()=>post('attachment',{attachment:ref.id}));}
function chips(){
  const nodes=[];
  for(const id of recipients){const b=btn('@'+(display(member(id))||id)+' ×',()=>{recipients=recipients.filter(v=>v!==id);saveDraft();chips();},'chip');nodes.push(b);}
  for(const f of room?.draft.attachments||[]){const box=el('span',undefined,'chip');const remove=actionLink('×',()=>post('detach',{attachment:f.id,key:currentKey}));remove.setAttribute('aria-label',tr('Remove ','移除 ')+f.name);box.append(attachment(f),remove);nodes.push(box);}
  $('chips').replaceChildren(...nodes);
}
function paintMentions(){
  const list=$('mentions');list.hidden=!mentions;list.replaceChildren();
  if(!mentions||!room)return;
  for(const m of room.members){
    const b=btn(display(m),()=>{
      const t=$('message'),p=t.selectionStart;
      if(p>0&&t.value[p-1]==='@')t.setRangeText('',p-1,p,'end');
      if(!recipients.includes(m.role))recipients.push(m.role);
      mentions=false;paintMentions();saveDraft();chips();t.focus();
    });
    b.prepend(face(m));list.append(b);
  }
}
function historyList(){
  const needle=$('search').value.trim().toLocaleLowerCase(),list=$('rooms');list.replaceChildren();
  for(const r of state.rooms||[]){
    const name=r.title||tr('New task','新建任务');if(!name.toLocaleLowerCase().includes(needle))continue;
    const b=btn('',()=>{saveDraft();post('select',{id:r.id});},'roomlink');
    b.setAttribute('aria-current',String(r.id===state.id));b.append(el('strong',name,'ellipsis'),el('small',label(r.state),'ellipsis'));list.append(b);
  }
}
function textBlock(text,id){
  const section=el('div'),long=text.length>1100,full=expanded.has(id);
  section.append(el('div',long&&!full?text.slice(0,1050)+'…':text,'bubble'));
  if(long)section.append(actionLink(full?tr('Show less','收起'):tr('Read more','展开全文'),()=>{full?expanded.delete(id):expanded.add(id);feedStamp='';renderFeed();}));
  return section;
}
function cardEntry({m,name,text,time,owner=false,tag='',key,extra}){
  const box=el('article',undefined,'entry'+(owner?' owner':'')),content=el('div',undefined,'content');
  if(m)box.append(face(m));box.append(content);
  const meta=el('div',undefined,'metadata');meta.append(el('strong',name));if(tag)meta.append(el('small',tag));
  if(time){const clock=el('small',new Date(time*1000).toLocaleTimeString(state.zh?'zh-CN':'en-US',{hour:'2-digit',minute:'2-digit'}));meta.append(clock);}
  content.append(meta);if(text)content.append(textBlock(text,key));if(extra)content.append(extra);return box;
}
function attemptStatus(a){
  if(a.state==='intent'||a.state==='sent'){
    if(a.transport==='completed')return tr('Reply received · verifying','已收到回复 · 核对中');
    if(a.transport==='accepted')return tr('Received by provider','提供方已接收');
    if(a.transport)return label(a.transport);
  }
  return label(a.state);
}
function renderFeed(){
  const log=$('feed');if(!room){log.replaceChildren();return;}
  const key=JSON.stringify([state.zh,room.id,room.inputs,room.answers,room.attempts,room.queue,room.supplements,room.undelivered,room.historyRows,room.rosterChanges,room.skippedCopies]);
  if(feedStamp===key)return;feedStamp=key;
  const nearEnd=log.scrollHeight-log.scrollTop-log.clientHeight<90,oldTop=log.scrollTop,rows=[];
  for(const a of room.historyRows||[])rows.push([a.time,cardEntry({name:a.member==="Owner"?tr("You","你"):a.member,text:a.text,tag:tr('Earlier round','历史轮次')+' · '+label(a.state),time:a.time,key:'old'+a.time})]);
  for(const change of room.rosterChanges||[])rows.push([change.time,cardEntry({name:'TWOS',text:change.members.map(m=>display(m)+' · '+(m.duties||[m.role]).map(label).join(', ')).join('\n'),tag:tr('Team updated','团队已更新'),time:change.time,key:'roster'+change.time})]);
  for(const m of room.inputs){
    const tags=m.recipients.map(id=>'@'+(display(m.members.find(p=>p.role===id))||id));
    const extra=el('div');
    for(const a of m.attachments)extra.append(attachment(a));
    const pending=room.queue.filter(q=>q.message===m.id&&['direct','coordinate'].includes(q.kind)).map(q=>display(member(q.member))||q.member);
    if(pending.length)extra.append(el('small',tr('Queued for ','待处理 · ')+pending.join(', ')));
    if(room.skippedCopies?.[m.id])extra.append(el('small',tr('Duplicate kept in history · skipped','重复消息已保留 · 已跳过派发')));
    for(const entry of (room.undelivered||[]).filter(x=>x.message===m.id))extra.append(el('small',(display(m.members.find(x=>x.role===entry.member))||entry.member)+' · '+tr('Member removed before delivery','成员已移除，消息未派发')));
    for(const s of room.supplements.filter(s=>s.message===m.id))extra.append(el('small',(display(member(s.member))||s.member)+' · '+label(s.state)));
    rows.push([m.time,cardEntry({name:tr('You','你'),text:m.text,owner:true,tag:tags.join(' '),time:m.time,key:m.id,extra})]);
  }
  for(const a of room.attempts){
    const reply=room.answers.find(x=>x.attemptID===a.id),m=reply?.member||a.snapshot||member(a.member);
    const detail=actionLink(label(a.kind)+' · '+attemptStatus(a)+' ›',()=>chooseTab('activity',a.id));
    rows.push([a.time,cardEntry({m,name:display(m)||a.member,text:reply?.text||'',tag:m?.product||'',time:a.time,key:a.id,extra:detail})]);
  }
  if(rows.length)log.replaceChildren(...rows.sort((a,b)=>a[0]-b[0]).map(r=>r[1]));
  else {const center=el('div',undefined,'welcome');center.append(row(...room.members.slice(0,6).map(face)),el('h2',tr('What are we working on?','今天一起做什么？')));log.replaceChildren(center);}
  log.scrollTop=nearEnd||formRoom!==room.id ? log.scrollHeight:oldTop;
}
function field(title,control){const wrap=el('label',title);wrap.append(control);return wrap;}
function selectBox(items,selected,change){
  const box=el('select');for(const [id,title] of items){const opt=new Option(title,id);box.add(opt);}box.value=selected;box.onchange=()=>change(box.value);return box;
}
function rosterEditor(){
  const form=el('section',undefined,'card editor'),m=edit.value;
  const name=el('input');name.value=m.displayName;name.maxLength=40;name.oninput=()=>{m.displayName=name.value;};
  const provider=selectBox(Object.keys(providers).map(p=>[p,p]),m.product,p=>{
    m.product=p;m.provider=providers[p];m.model='';delete m.effort;renderSide(true);
  });
  form.append(row(face(m),el('strong',tr('Member settings','成员设置'))),field(tr('Name','姓名'),name),field(tr('Provider','提供方'),provider));
  if(m.product==='Codex'){
    const catalog=room.catalog||[],rows=catalog.map(v=>[v.model,v.displayName||v.model]);
    if(m.model&&!rows.some(r=>r[0]===m.model))rows.unshift([m.model,m.model]);
    const model=selectBox([['',tr('Connection default','连接默认选择')],...rows],m.model,v=>{m.model=v;m.effort='';renderSide(true);});
    const levels=catalog.find(v=>v.model===m.model)?.supportedReasoningEfforts||[];
    const options=levels.map(e=>[e.reasoningEffort,e.reasoningEffort]);
    if(m.effort&&!options.some(o=>o[0]===m.effort))options.push([m.effort,m.effort]);
    form.append(field(tr('Model','模型'),model),field(tr('Effort','强度'),selectBox([['',tr('Model default','模型默认')],...options],m.effort||'',v=>{m.effort=v;})));
  } else {
    form.append(el('small',m.model||tr('Use the selection on the provider website.','使用提供方网页中的选择。')),el('small',tr('Adjust supported effort on the provider website.','可用强度在提供方网页调整。')));
  }
  if(member(m.role)?.product===m.product)form.append(btn(tr('Open connection','打开成员连接'),()=>post('channel',{member:m.role})));
  const set=el('fieldset');set.append(el('legend',tr('Responsibilities','职责')));
  const originals=m.duties||[m.role];m.duties=[...originals];
  for(const d of duties){const b=el('input');b.type='checkbox';b.checked=m.duties.includes(d);b.onchange=()=>{m.duties=b.checked?[...m.duties,d]:m.duties.filter(v=>v!==d);};const l=el('label');l.append(b,document.createTextNode(label(d)));set.append(l);}
  const custom=el('input');custom.placeholder=tr('Custom responsibility','自定义职责');custom.value=originals.filter(d=>!duties.includes(d)).join(' / ');custom.maxLength=120;
  form.append(set,custom,el('small',tr('Changes apply to future assignments.','更改在后续分派时生效。')));
  const apply=btn(tr('Save','保存'),()=>{
    m.duties=[...m.duties.filter(d=>duties.includes(d)),...custom.value.split(' / ').map(x=>x.trim()).filter(Boolean)];
    const roster=room.members.map(p=>p.role===m.role?m:p);
    if(!roster.some(p=>p.role===m.role))roster.push(m);
    if(!m.displayName.trim()||!m.duties.length){localError('invalidRoster');return;}
    post('roster',{members:roster});edit=null;renderSide(true);
  },'primary');
  form.append(row(apply,btn(tr('Cancel','取消'),()=>{edit=null;renderSide(true);})));
  if(m.role!==slots[0]&&room.members.some(x=>x.role===m.role))form.append(btn(tr('Remove member','移除成员'),()=>{post('roster',{members:room.members.filter(x=>x.role!==m.role)});edit=null;renderSide(true);}));
  return form;
}
function startEdit(m){edit={value:JSON.parse(JSON.stringify(m))};tab='members';$('inspector').classList.add('open');renderSide(true);}
function renderSide(force=false){
  const detail=$('detail');if(!room){detail.replaceChildren();return;}
  const summary=JSON.stringify([room.id,state.zh,tab,focusAttempt,room.members,room.attempts,room.plans,room.files,room.path,room.verdict,room.revision,room.mismatch,room.state,room.catalog]);
  if(!force&&(summary===sideStamp||edit&&detail.querySelector('.editor')?.contains(document.activeElement)))return;
  sideStamp=summary;detail.replaceChildren();
  for(const id of ['members','activity','files'])$(id+'Tab').setAttribute('aria-selected',String(id===tab));
  if(tab==='members'){
    if(edit){detail.append(rosterEditor());return;}
    detail.append(el('h2',tr('Team members','团队成员')+' · '+room.members.length+'/6'));
    for(const m of room.members){
      const c=el('div',undefined,'card');c.append(row(face(m),el('strong',display(m))),el('div',(m.duties||[m.role]).map(label).join(' · ')),
        el('small',[m.product,m.model,m.effort].filter(Boolean).join(' · ')),row(actionLink(tr('Edit','编辑'),()=>startEdit(m)),actionLink(tr('Open connection','打开连接'),()=>post('channel',{member:m.role}))));if(m.product!=='Codex')c.append(actionLink(tr('Use current website selection','采用网页当前选择'),()=>post('adoptSelection',{member:m.role})));
      detail.append(c);
    }
    const add=btn(room.members.length===6?tr('Six-member limit','已达六名上限'):tr('＋ Add member','＋ 添加成员'),()=>{
      const i=slots.findIndex(s=>!member(s)),s=slots[i];if(i<0)return;
      startEdit({role:s,displayName:faces[i][0].toUpperCase()+faces[i].slice(1),product:'Codex',provider:'OpenAI',model:'',duties:[s==='Compliance'?'Compliance reviewer':s]});
    });add.disabled=room.members.length>=6;detail.append(add);
  } else if(tab==='activity'){
    for(const plan of room.plans||[]){const d=el('details',undefined,'card');d.append(el('summary',tr('Task plan','任务计划')),el('div',plan.requirements.join('\n'),'details'));detail.append(d);}
    const rows=focusAttempt?room.attempts.filter(a=>a.id===focusAttempt):[...room.attempts].reverse();
    if(focusAttempt)detail.append(actionLink(tr('All activity','全部活动'),()=>chooseTab('activity')));
    if(!rows.length)detail.append(el('p',tr('No dispatches yet.','尚未派发。'),'empty'));
    for(const a of rows){
      const d=el('div',undefined,'card');d.append(el('strong',(display(a.snapshot||member(a.member))||a.member)+' · '+label(a.kind)),el('div',attemptStatus(a)));
      d.append(el('small',tr('Requested','请求模型')+' · '+(a.requested||tr('Unknown','未知'))),
        el('div',tr('Reported','回报模型')+' · '+(a.actual||tr('Unconfirmed','未核实')),'small'));
      for(const x of a.activity)d.append(el('div',[x.kind,x.status,x.text].filter(Boolean).join(' · '),'details'));
      if(a.text&&!room.answers.some(x=>x.attemptID===a.id))d.append(textBlock(a.text,'receipt'+a.id));
      detail.append(d);
    }
  } else {
    detail.append(el('h2',tr('Output folder','成果目录')),el('p',room.path||tr('Choose a folder when files are needed.','需要生成文件时选择目录。'),'details'),
      btn(tr('Choose folder','选择目录'),()=>post('directory')));
    if(room.path)detail.append(btn(tr('Open folder','打开目录'),()=>post('openFolder')));
    if(room.updated)detail.append(el('p',new Date(room.updated*1000).toLocaleString(state.zh?'zh-CN':'en-US'),'small'));
    for(const path of room.files){
      const c=el('div',undefined,'card');c.append(el('strong',path),el('div',!room.currentFiles.includes(path)?tr('Earlier version','较早版本'):room.mismatch===room.revision?label('fileConflict'):room.verdict?label(room.verdict):tr('Draft · in review','草稿 · 待审核'),'small'));
      for(const [mode,title] of [['preview',tr('Preview','预览')],['open',tr('Open','打开')],['reveal',tr('Show in Finder','在 Finder 中显示')]])c.append(actionLink(title,()=>post('file',{path,mode})));
      detail.append(c);
    }
    if(room.state==='awaitingOwner')detail.append(btn(tr('Accept this version','接受此版本'),()=>post('accept',{version:room.revision}),'primary'));
  }
  detail.append(btn(tr('Close details','关闭详情'),()=>{$('inspector').classList.remove('open');},'narrowclose subtle'));
}
function localError(k){errorLocal=k;notice();}
const connectionCopy={
  reviewerChat:['Open a fresh chat in this member window or return to its assigned chat.','请在这个成员窗口打开空白对话，或回到该成员已绑定的对话。'],
  reviewerUnavailable:['Check this member’s connection before continuing.','请先检查这位成员的连接。'],
  reviewerChanged:['The website selection differs from the member settings.','网页当前选择与成员设置不一致。'],
  checkingConnection:['Checking the connection…','正在检查连接…'],
  webLogin:['Sign in in this member’s window. Then return here to continue.','请在这位成员的窗口登录，完成后回到群聊继续。'],
  webVerification:['Complete the website verification, then return here.','请在成员窗口完成网站验证，再回到群聊。'],
  webLoading:['The member’s page is loading. Check again when it opens.','成员网页正在加载，打开后请重新检查。'],
  webComposer:['The member’s page has no unambiguous message box yet. Open it to check.','尚未识别到唯一输入框，请打开成员网页检查。'],
  webSelection:['Could not confirm the website’s model or signed-in default. Check the model in the member window.','尚未确认网页模型或已登录的默认选择，请在成员窗口核对模型。'],
  webMismatch:['Switch the website to the member’s model, or adopt the current selection under Members.','请切换到成员设定的模型，或在成员栏采用网页当前选择。'],
  webUnavailable:['The member’s page could not be verified. Open it and refresh the connection.','暂时无法确认成员网页，请打开该窗口后重新检查。'],
  webReady:['Connection ready. Continue the queued message without typing it again.','连接已就绪，可直接继续这条待发消息。'],
  webBusy:['The provider is still replying. Check again after it finishes.','提供方正在回复，结束后请重新检查。'],
  webDraft:['The member’s window has a draft. Save or clear it, then check again.','成员窗口中有草稿，请先保留或清空，再重新检查。'],
  webLimit:['The provider reported a usage or capacity limit. Check its window before continuing.','提供方提示用量或服务容量受限，请查看成员窗口后再继续。'],
  codexUnavailable:['Open local Codex and check the connection and chosen model.','请打开本机 Codex，核对连接和所选模型。']
};
function recoveryNotice(target,recovery){
  if(recovery.retained){
    const name=display(member(recovery.member))||recovery.member;
    const copy={
      checkingConnection:['Checking the original conversation…','正在核对原会话…'],
      retainedExact:['The original draft matches. Send it once here, or send it in the member window and return to check.','已核对原草稿。可在这里发送一次，也可在成员窗口发送后返回核对。'],
      retainedEmpty:['The original composer is empty. Check the member window. If you have never sent this draft there, you can restore its text.','原输入框已空。请检查成员窗口。如确认从未手动发送，可以恢复原草稿。'],
      retainedChanged:['The composer contains different text. Open the member window to review it.','输入框中已有其他内容，请打开成员窗口核对。'],
      retainedCheck:['Open the original conversation to locate the draft or the sent message, then check again.','请打开成员窗口找到原草稿或已发送消息，再回来核对。'],
      retainedDraft:['The website did not send this draft.','这份网页草稿尚未发送。']
    };
    target.hidden=false;
    target.append(el('strong',name+' · '+recovery.provider),el('span',tr(...(copy[recovery.state]||copy.retainedDraft))));
    const actions=row();
    if(recovery.state==='retainedExact')
      actions.append(btn(tr('Send verified draft','发送已核对的草稿'),()=>post('sendRetained',{step:recovery.step}),'primary'));
    if(recovery.state==='retainedEmpty')
      actions.append(btn(tr('I have not sent it · restore draft','确认未发送，恢复草稿'),()=>post('restoreDraft',{step:recovery.step}),'primary'));
    const check=btn(tr('Check original conversation','核对原会话'),()=>post('checkConnection',{step:recovery.step}));
    check.disabled=recovery.state==='checkingConnection';
    actions.append(check,actionLink(tr('Open member window','打开成员窗口'),()=>post('channel',{member:recovery.member})));
    target.append(actions);return;
  }
  const m=member(recovery.member), message=connectionCopy[recovery.state]||connectionCopy.webUnavailable;
  target.hidden=false;
  target.append(el('strong',(display(m)||recovery.member)+' · '+recovery.provider),el('span',tr(...message)));
  const actions=row();
  if(recovery.state==='webReady'){
    const copies=recovery.duplicates||0;
    actions.append(btn(copies?tr('Continue once · skip duplicate copies','继续一次，跳过重复消息'):tr('Continue queued message','继续待发消息'),
      ()=>post('continueConnection',{step:recovery.step,skipCopies:copies>0}),'primary'));
    if(copies)actions.append(actionLink(tr('Keep and send all','保留并继续全部'),()=>post('continueConnection',{step:recovery.step,skipCopies:false})));
  }else{
    const open=btn(recovery.state==='webLogin'?tr('Sign in to ','登录 ')+recovery.provider:tr('Open connection','打开成员连接'),
      ()=>post('channel',{member:recovery.member}),'subtle');
    const check=btn(recovery.state==='checkingConnection'?tr('Checking…','正在检查…'):tr('Refresh connection','刷新连接'),
      ()=>post('checkConnection',{step:recovery.step}),'primary');
    check.disabled=recovery.state==='checkingConnection';actions.append(open,check);
  }
  target.append(actions);
  if(recovery.checked && recovery.state!=='webReady')target.append(el('small',tr('Last checked ','上次检查 ')+new Date(recovery.checked*1000).toLocaleTimeString()));
}
function notice(){
  const target=$('notice');target.replaceChildren();
  const recovery=room?.recovery;
  target.classList.toggle('recovery',!!recovery?.step);
  if(recovery?.step){
    recoveryNotice(target,recovery);
    if(state.error||errorLocal)target.append(el('small',label(state.error||errorLocal)));
    return;
  }
  const msgs=[errorLocal,state.error,room?.reason,room?.issue,room?.channelNotice].filter(Boolean);
  const text=[...new Set(msgs)].map(label).join(' · ');target.hidden=!text;
  if(!text)return;
  target.append(el('span',text));
  if(msgs.includes('outputNeeded'))target.append(actionLink(tr('Choose folder','选择目录'),()=>post('directory')));
  if(room && ['paused','blocked','stopping'].includes(room.state)&&!room.stop)
    target.append(actionLink(tr('Reconcile','核对状态'),()=>post('reconcile')));
}
window.renderTeam=next=>{
  const prevRoom=room?.id;state=next;room=next.room;
  document.documentElement.lang=state.zh?'zh-CN':'en';
  const text={new:tr('＋ New task','＋ 新建任务'),import:tr('Load earlier chats','载入旧版群聊'),stop:tr('Stop','停止'),settings:tr('Details','详情'),
    membersTab:tr('Members','成员'),activityTab:tr('Activity','执行过程'),filesTab:tr('Files','成果文件'),send:tr('Send ↑','发送 ↑')};
  for(const [id,v] of Object.entries(text))$(id).textContent=v;
  $('search').placeholder=tr('Find a chat','查找群聊');$('search').setAttribute('aria-label',$('search').placeholder);
  $('message').placeholder=tr('Tell your team what you want to accomplish','告诉团队你想完成什么');$('message').setAttribute('aria-label',$('message').placeholder);
  $('attach').setAttribute('aria-label',tr('Attach files','添加附件'));$('mention').setAttribute('aria-label',tr('Mention members','提及成员'));
  $('new').disabled=!state.writable;$('stop').hidden=!room||!['running','paused','stopping'].includes(room.state);$('stop').disabled=room?.state==='stopping';
  $('title').textContent=room?.goal||tr('New task','新建任务');$('roomLabel').textContent=room?label(room.state):'AI Team';
  const l=$('language');l.setAttribute('aria-label',tr('Output language','输出语言'));l.replaceChildren(...[['auto',tr('Auto language','自动语言')],['zh-CN','简体中文'],['en','English']].map(([v,t])=>new Option(t,v)));l.value=room?.language||'auto';
  const m=room?.members[0];$('config').textContent=m?[m.product,m.model,m.effort].filter(Boolean).join(' · '):'';$('config').title=tr('Coordinator settings','协调者设置');
  if(prevRoom!==room?.id){edit=null;focusAttempt='';expanded.clear();mentions=false;errorLocal='';feedStamp='';sideStamp='';composing=false;}
  if(room && (formRoom!==room.id || currentKey!==room.draft.key)){
    $('message').value=room.draft.text||'';recipients=[...room.draft.recipients];currentKey=room.draft.key;sending='';mentions=false;
  }else if(state.error&&sending){sending='';}
  historyList();renderFeed();renderSide();chips();paintMentions();notice();updateSend();formRoom=room?.id||'';
};
$('new').onclick=()=>{saveDraft();post('new');};$('import').onclick=()=>post('import');$('search').oninput=historyList;
$('stop').onclick=()=>post('stop');$('settings').onclick=()=>chooseTab(tab);$('config').onclick=()=>{if(room)startEdit(room.members[0]);};
for(const t of ['members','activity','files'])$(t+'Tab').onclick=()=>chooseTab(t);
$('language').onchange=e=>post('language',{language:e.target.value});$('attach').onclick=()=>post('attach',{key:currentKey});
$('mention').onclick=()=>{mentions=!mentions;paintMentions();};$('send').onclick=send;
const input=$('message');
input.oncompositionstart=()=>{composing=true;};input.oncompositionend=()=>{composing=false;saveDraft();updateSend();};
input.oninput=()=>{errorLocal='';if(!composing)saveDraft();updateSend();if(!composing&&/(?:^|\s)@$/.test(input.value.slice(0,input.selectionStart))){mentions=true;paintMentions();}};
input.onkeydown=e=>{if(e.isComposing||composing||e.keyCode===229)return;if(e.key==='Escape'){mentions=false;paintMentions();}if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();if(!e.repeat)send();}};
async function upload(files){
  if(!room||!files.length)return;
  const target=room.id,key=currentKey;
  if(files.length>8||files.some(f=>f.size>8000000)||files.reduce((n,f)=>n+f.size,0)>12000000){localError('tooLarge');return;}
  try{
    const parts=await Promise.all(files.map(f=>new Promise((ok,no)=>{const r=new FileReader();r.onerror=no;r.onload=()=>ok({name:f.name,bytes:String(r.result).split(',')[1]});r.readAsDataURL(f);})));
    if(room.id!==target||currentKey!==key){localError('wrongVersion');return;}post('upload',{key,files:parts});
  }catch{localError('attachmentUnsupported');}
}
input.onpaste=e=>{const files=Array.from(e.clipboardData?.files||[]);if(files.length){e.preventDefault();upload(files);}};
document.addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();$('compose').classList.add('drop');}});
document.addEventListener('dragleave',e=>{if(!e.relatedTarget)$('compose').classList.remove('drop');});
document.addEventListener('drop',e=>{e.preventDefault();$('compose').classList.remove('drop');upload(Array.from(e.dataTransfer.files));});
