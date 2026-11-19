'use strict';
const roles = ['Planner', 'Builder', 'Reviewer'];
const names = {Planner:'Ada',Builder:'Kai',Reviewer:'Ren'};
const services = ['Codex', 'ChatGPT', 'Claude', 'DeepSeek'];
const messageDrafts=new Map();
let following = true, selection = '', selectedRoom = '', needle = '', compose = '', pendingMessage = null;
let state, draft = {goal: null, csv: null, planner: '', builder: '', reviewer: '', quota: false, comment: ''},
           editing = false, preview = false, pageKey = '';
const tr = (en, zh) => state.zh ? zh : en;
const by = id => document.getElementById(id);
const send = (action, values = {}) =>
    window.webkit.messageHandlers.team.postMessage({action, ...values});
const node = (tag, txt, cls) => {
  const e = document.createElement(tag);
  if (txt != null) e.textContent = txt;
  if (cls) e.className = cls;
  return e
};
const role = r => ({
                    Planner: tr('Planner', '负责人'),
                    Builder: tr('Builder', '制作者'),
                    Reviewer: tr('Reviewer', '独立审核者')
                  })[r] ||
    r;
function modelLabel(model) {
  if (!model) return '';
  const effort = {
    '超高': ['Extra high', '超高'],
    '高': ['High', '高'],
    '中': ['Medium', '中等'],
    '中等': ['Medium', '中等'],
    '低等': ['Low', '低'],
    'xhigh': ['Extra high', '超高'],
    '低': ['Low', '低'],
    'extra high': ['Extra high', '超高'],
    'high': ['High', '高'],
    'medium': ['Medium', '中等'],
    'low': ['Low', '低']
  };
  return model.replace(
      /\s+(超高|高|中等|中|低等|低|extra high|xhigh|high|medium|low)$/i,
      (_, v) => ' · ' + tr(...effort[v.toLowerCase()]));
}
const messages = {
  decisionConflict:['The saved decision is waiting for its verified files. Inspect the files and retry.','已记录决定，等待核对原交付文件。核实文件后可重试。'],
  archiveError:['Some earlier chats could not be loaded.','部分旧群聊无法读取。'],
  archiveLoaded:['Earlier chats have been indexed. Open them in the chat list.','已载入旧群聊，可从左侧打开。'],
  unsent: ['Not sent', '未发送'],
  failed: ['Execution failed', '执行失败'],
  rejected: ['Request declined', '请求被拒绝'],
  stopUnconfirmed: [
    'Dispatch is stopped. The last operation has no terminal receipt. Reconcile the saved operation.',
    '后续派发已禁止。最后一次操作尚无终态回执，请核对原操作。'
  ],
  exportRetry: [
    'The verified files are ready. Use Save delivery to retry writing the folder.',
    '文件已通过校验。请点「保存交付」重试写入。'
  ],
  noApproval:
      ['There is no permission request for this exact team turn.', '当前团队轮次没有待处理权限请求。'],
  deliveryFolderUnavailable: ['Choose a writable project folder.', '请选择可写入的项目目录。'],
  invalidInput: [
    'Use a goal and a two-column CSV with non-negative amounts and at most two decimal places.',
    '请填写目标并提供两列 CSV，金额非负，最多两位小数。'
  ],
  unavailable: [
    'Check the output folder and each member’s selected provider and model.',
    '请检查交付目录和每个成员的提供方及型号。'
  ],
  scope: [
    'The approved task folder or native session could not be confirmed.',
    '无法确认批准的目录或本地任务会话。'
  ],
  identity: [
    'The provider did not confirm the approved model for every reply. Cross-model acceptance is pending.',
    '服务方未逐次确认所批准的模型，跨模型验收待核对。'
  ],
  readingMemberSelection: ['Reading the member’s current model selection…','正在读取该成员当前的型号设置…'],
  reviewerChanged: [
    'The selected model is unavailable or changed. Check it in the member’s conversation.',
    '当前无法确认已批准的型号，请在成员会话中核对。'
  ],
  reviewFormat: [
    'The review was tied to these files, but its format could not certify a decision. The feedback is available for revision.',
    '审核回复对应本版文件，但格式无法确认正式结论。返工时可查看原反馈。'
  ],
  reviewerLoading: [
    'Restoring the original review. Once it loads, check the saved reply again.',
    '正在恢复原审核会话，载入后可再次核对已存回复。'
  ],
  reviewerDraft: [
    'The role’s website retained the original draft. Open its conversation, check and send that draft once, then reconcile.',
    '该成员的网页保留了原草稿。打开该成员会话核对原稿，确认无误后只发送一次，再点「核对并继续」。'
  ],
  reviewerChat: [
    'Open a new chat for this member or restore their original conversation.',
    '请打开此成员的新聊天，或恢复本任务绑定的原会话。'
  ],
  reviewerUnavailable: [
    'Check the member’s web conversation and delivery receipt before continuing.',
    '请检查该成员的网页窗口和交接回执再继续。'
  ],
  storage: ['The local run record could not be saved or read safely.', '无法安全读写本地运行记录。'],
  busy: ['Another team session already owns this task.', '其他团队会话已占用此任务。'],
  timeout: ['Time limit reached. Future dispatches stopped.', '已到时限，已停止后续派发。'],
  reworkLimit: ['The two-revision limit was reached.', '已达两次返工上限。'],
  unconfirmed: [
    'Delivery is uncertain. Check the original operation. It will not be resent.',
    '送达待核对。请检查原操作，系统不会重发。'
  ],
  restart: [
    'The app restarted. Reconcile the saved operation to continue.',
    '应用已重启。核对此前操作后可继续。'
  ],
  reconciling: ['Checking the saved operation.', '正在核对原操作。'],
  codexUnavailable: [
    'Reconnect the official local Codex to restore the selected model.',
    '请连接官方本地 Codex 并恢复所选模型。'
  ],
  approvalRequired: [
    'An execution permission request is waiting in the team Codex pane.',
    '团队 Codex 有一项权限请求，请在该任务窗口处理。'
  ],
  invalidReply: ['The reply did not follow the agreed file format.', '回复不符合约定的文件格式。'],
  invalidReview: ['Independent review did not match the required format.', '独立审核格式不符合要求。'],
  wrongVersion:
      ['The review or exported files refer to a different version.', '审核或导出文件的版本不一致。'],
  invalidReport: [
    'The report is missing supported bilingual content or rows.', '报告缺少合规的中英文内容或数据行。'
  ],
  changedDirectory: ['The selected folder changed identity.', '所选目录的身份已变化。'],
  budgetExceeded:
      ['The approved dispatch or time limit was reached.', '已到批准的派发次数或时间上限。'],
  stopped: ['Future dispatches have stopped.', '已停止后续派发。'],
  running: ['Running', '执行中'],
  checkingResult: ['Checking the returned result', '正在核对返回结果'],
  queued: ['Queued', '已排队'],
  sending: ['Sending', '正在发送'],
  statusPending: ['Current status unavailable', '状态待确认'],
  stopping: ['Stopping; awaiting terminal receipt', '正在停止，等待终态回执'],
  paused: ['Paused', '已暂停'],
  blocked: ['Needs attention', '需要处理'],
  awaitingOwner: ['Delivery ready for your decision', '交付待你验收'],
  accepted: ['Delivery accepted', '已接受交付'],
  changes: ['Changes requested', '已记录修改意见'],
  intent: ['Dispatch recorded', '已记录派发意图'],
  sent: ['Sent', '已送达'],
  completed: ['Completed', '已完成'],
  interrupted: ['Interrupted', '已中断'],
  cancelled: ['Cancelled', '已取消']
};
const message = k => messages[k] ? tr(...messages[k]) : k;
function button(parent, label, fn, primary = false) {
  const e = node('button', label, primary ? 'primary' : '');
  e.onclick = fn;
  parent.append(e);
  return e
}
function field(parent, id, label) {
  const l = node('label', label);
  l.htmlFor = id;
  const e = node('textarea');
  e.id = id;
  e.rows = id === 'csv' ? 5 : 2;
  e.value = draft[id];
  e.oninput = () => {
    draft[id] = e.value;
    if(id==='goal'||id==='csv')send('draft',{[id]:e.value})
  };
  parent.append(l, e)
}
function actions(parent) {
  const a = node('div', null, 'actions');
  parent.append(a);
  return a
}
function safeJSON(raw, fallback) {
  try { return typeof raw === 'string' ? JSON.parse(raw) : raw ?? fallback }
  catch { return fallback }
}
function localText(value) { return value?.[state.zh ? 'zh' : 'en'] || value?.en || value?.zh || '' }
function stamp(seconds) {
  return seconds ? new Date(seconds * 1000).toLocaleString(state.zh ? 'zh-CN' : 'en',
    {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : ''
}
function person(name, service = '', model = '', alias = '') {
  const row = node('div', null, 'person');
  alias=alias||state.run?.members.find(m=>m[0]===name)?.[3]||'';
  const display = name === 'Owner' ? tr('You','你') : name === 'TWOS' ? 'TWOS' : role(name);
  const faces = {Planner:'ada',Builder:'kai',Reviewer:'ren',Supervisor:'mira',Tester:'sol',Compliance:'lou'};
  const avatar = faces[name] ? node('img',null,'avatar') : node('span',display,'avatar');
  if (faces[name]) { avatar.src='avatars/'+faces[name]+'.png'; avatar.alt=alias||display }
  else { avatar.setAttribute('aria-hidden','true') }
  const info = node('div'); info.append(node('strong',alias?alias+' · '+display:display));
  if (service || model) info.append(node('small',[service,modelLabel(model)].filter(Boolean).join(' · ')));
  row.append(avatar,info); return row
}
function serviceFor(r) { return state.services[r] }
function chosen(r) {
  const provider = serviceFor(r);
  return provider === 'Codex' ? draft[r.toLowerCase()] : state.webModels[r + '-' + provider] || ''
}
function options(parent, label, list, value, change, id) {
  const l=node('label',label), s=node('select'); s.id=id; l.htmlFor=id;
  for(const item of list){const o=node('option',item);o.value=item;s.append(o)}
  s.value=value;s.onchange=()=>change(s.value);parent.append(l,s);return s
}
function channels(p) {
  const grid=node('div',null,'roles');p.append(grid);
  for (const r of roles) {
    const card=node('div',null,'role-card'), service=serviceFor(r);
    const name = r.toLowerCase();
    card.append(person(r,'','',names[r]));
    const nameLabel=node('label',tr('Name','名字')),input=node('input');
    input.type='text';input.id=name+'-name';nameLabel.htmlFor=input.id;input.maxLength=32;input.value=names[r];
    input.oninput=()=>{names[r]=input.value;draft.quota=false;send('draft',{[r+'Name']:input.value})};
    card.append(nameLabel,input);
    options(card,tr('Provider','提供方'),services,service,v=>{draft.quota=false;send('service',{role:r,service:v})},name+'-provider');
    if(service==='Codex'){
      const select=options(card,tr('Model','型号'),state.catalog,chosen(r),v=>{draft[name]=v;draft.quota=false;send('draft',{[r]:v});renderLocal()},name+'-model');
      select.disabled=!state.catalog.length;
      if(!state.catalog.length)card.append(node('small',tr('Waiting for the local model list.','等待本地型号清单。')))
    } else {
      card.append(node('p',modelLabel(chosen(r)) || tr('Selected model pending','待确认所选型号'),'small'));
      button(card,tr('Choose in ','在 ')+service+tr('…',' 中选择…'),()=>send('reviewer',{role:r}));
    }
    grid.append(card)
  }
}
function params() {
  const args={goal:draft.goal,csv:draft.csv};
  for(const r of roles){args[r.toLowerCase()]=chosen(r);args[r+'Service']=serviceFor(r);args[r+'Name']=names[r].trim()||role(r)}
  return args
}
function rosterIssue() {
  if (!state.folder) return tr('Choose a delivery folder.','请选择交付目录。');
  if (roles.some(r=>!chosen(r))) return tr('Select an identifiable model for each member in its provider.','请为每位成员选择可识别的型号。');
  const suppliers=roles.map(r=>['ChatGPT','Codex'].includes(serviceFor(r))?'OpenAI':serviceFor(r));
  if(new Set(suppliers).size<2 || chosen('Builder')===chosen('Reviewer'))
    return tr('Use two suppliers and different Builder and Reviewer models.','团队需含两家供应商，制作者和审核者需使用不同型号。');
  return ''
}
function scope(p) {
  p.append(node('p',tr('Each selected provider receives the approved goal and CSV. The reviewer receives the frozen files. Up to seven dispatches, two revisions and 45 minutes. Extra paid budget is zero.',
    '所选供应商会收到批准的目标和 CSV，审核者还会收到冻结文件。最多派发七次、返工两次、用时 45 分钟，额外付费上限为零。'),'small'))
}
function form(p) {
  field(p,'goal',tr('What should the team deliver?','你希望团队交付什么？'));
  field(p,'csv',tr('Regional sales data · CSV','区域销售数据 · CSV'));
  const a=actions(p);
  button(a,tr('Choose CSV…','选择 CSV…'),()=>send('csv'));
  button(a,tr('Choose delivery folder…','选择交付目录…'),()=>send('directory'));
  p.append(node('p',state.folder || tr('Choose a folder. This task creates its own delivery subfolder.','选择已有目录，本任务会创建专属交付子目录。'),'small'));
  if(editing)channels(p);
  button(actions(p),tr('View recommended team','查看推荐团队'),()=>{
    preview=true;renderLocal()
  },true).disabled=!state.writable
}
function previewRoster(p) {
  p.append(node('p',draft.goal));channels(p);scope(p);
  const warning=rosterIssue();if(warning)p.append(node('p',warning,'warning'));
  const a=actions(p);
  button(a,tr('Choose folder…','选择目录…'),()=>send('directory'));
  button(a,tr('Adjust team or goal','调整成员或目标'),()=>{editing=true;preview=false;renderLocal()});
  button(a,tr('Review approval','核对并批准'),()=>send('propose',params()),true).disabled=!!warning||!state.writable
}
function proposal(p,q) {
  p.append(node('p',q.goal));
  for(const [r,s,m,n] of q.members)p.append(person(r,s,m,n));
  p.append(node('p',q.directory,'small'));scope(p);
  const label=node('label',null,'check'),check=node('input');check.type='checkbox';check.checked=draft.quota;
  label.append(check,document.createTextNode(tr('Use included quota only. Paid overage is disabled for the selected accounts.',
    '仅用已有额度；所选账户已关闭额外付费。')));p.append(label);
  const a=actions(p),start=button(a,tr('Approve and open group chat','批准并建立群聊'),()=>{
    start.disabled=true;send('approve',{id:q.id,quota:'confirmed'})
  },true);start.disabled=!draft.quota;
  check.onchange=()=>{draft.quota=check.checked;start.disabled=!check.checked};
  button(a,tr('Adjust members or goal','调整成员或目标'),()=>{draft.quota=false;preview=true;send('edit')})
}
function library() {
  by('historyTitle').textContent=tr('Team chats','团队群聊');
  const start=by('new-task');
  start.textContent=tr('New task','新建任务');
  start.disabled=!state.canNew;
  start.title=start.disabled?tr('Finish or stop the current task first.','请先完成或停止当前任务。'):'';
  start.onclick=()=>{
    document.body.classList.remove('show-library','show-detail');
    if(state.current){
      preview=false;editing=false;draft.quota=false;draft.goal=null;draft.csv=null;
      send('new',{id:state.current});
    }else if(state.archived){send('current')}
    else if(state.proposal){preview=false;editing=false;send('edit')}
    else{preview=false;editing=false;renderLocal();by('goal')?.focus()}
  };
  const search=by('search');search.placeholder=tr('Find a task…','搜索任务…');search.setAttribute('aria-label',search.placeholder);
  search.oninput=()=>{needle=search.value;rooms()};rooms()
}
function rooms(){
  const nav=by('rooms');nav.replaceChildren();
  const rows=state.history.filter(x=>x.title.toLowerCase().includes(needle.toLowerCase().trim()));
  for(const item of rows){
    const b=button(nav,'',()=>{document.body.classList.remove('show-library');send('history',{id:item.id})});
    b.className='room'+(state.run?.id===item.id?' selected':'');
    b.append(node('strong',item.title),node('small',stamp(item.created)+' · '+message(item.state)))
  }
  if(!rows.length)nav.append(node('p',needle?tr('No matching tasks.','没有匹配的任务。'):tr('Approved tasks appear here.','批准后的任务会保存在这里。'),'small'));
  if(state.canImport)button(nav,tr('Load earlier preview chats','载入旧版群聊'),()=>send('import')).disabled=state.loadingHistory;
  if(state.archiveIssues)nav.append(node('small',tr('Some saved records could not be read.','部分历史记录暂时无法读取。')))
}
function memberStatus(a) {
  if(state.archived || !['intent','sent','unknown'].includes(a.state))return message(a.state);
  if(state.run?.state==='stopping')return message('stopping');
  if(state.run?.state!=='running')return message('statusPending');
  if(a.service==='Codex' && a.dispatch){
    if(state.codex!=='connected')return message('statusPending');
    if(a.dispatch==='completed')return message('checkingResult');
    if(['queued','sending','running','interrupted','cancelled'].includes(a.dispatch))return message(a.dispatch)
  }
  return message(a.state)
}
function headline(a) {
  const plan=safeJSON(a.plan,null),report=safeJSON(a.report,null),review=safeJSON(a.review,null);
  if(plan)return [tr('Builder','制作')+' · '+localText(plan.builder),tr('Reviewer','审核')+' · '+localText(plan.reviewer),tr('Acceptance','验收')+' · '+localText(plan.acceptance)].join('\n');
  if(report)return localText(report.summary);
  if(review)return (review.verdict==='approve'?tr('Approved','审核通过'):tr('Revision requested','需要返工'))+' · '+localText(review.findings);
  if(a.feedback)return a.feedback;
  if(a.reply)return a.reply;
  return memberStatus(a)
}
function entry(feed,id,name,subtitle,body,selectable=true) {
  const e=node(selectable?'button':'article',null,'entry');
  if(selectable){
    e.type='button';e.setAttribute('aria-pressed',String(selection===id));
    e.onclick=()=>{following=false;selection=id;document.body.classList.remove('show-library');document.body.classList.add('show-detail');renderLocal()}
  }
  e.append(person(name,subtitle),node('p',body,'text-preview'));feed.append(e);return e
}
function chat(p,r) {
  const status=node('p',message(r.state),'small');status.id='run-status';p.append(status);
  const feed=node('div',null,'feed');feed.setAttribute('aria-label',tr('Group conversation','群聊记录'));p.append(feed);
  entry(feed,'goal','Owner',stamp(r.created),r.goal);
  const approved=entry(feed,'roster','TWOS',tr('Team approved','团队已批准'),r.members.map(([n,s,m])=>role(n)+' · '+s+' · '+modelLabel(m)).join('\n'));
  approved.title=tr('Inspect the approved roster','查看已批准的名单');
  const timeline=[];
  for(const a of r.chat){
    const line=()=>entry(feed,a.id,a.role,[a.service,modelLabel(a.requested),'v'+a.version,stamp(a.started)].filter(x=>x!=='v0').join(' · '),
      tr('Assigned','已指派')+' · '+memberStatus(a));
    timeline.push([a.started,line]);
    if(a.reply||a.plan||a.report||a.review||a.feedback){
      const reply=()=>entry(feed,a.id,a.role,tr('Result','结果')+' · '+(a.version?'v'+a.version+' · ':'')+message(a.state),headline(a));
      timeline.push([a.finished || a.started,reply])
    }
  }
  for(const m of safeJSON(r.messages,[]))timeline.push([m.time,()=>entry(feed,'','Owner',stamp(m.time)+' · '+(m.share?tr('For upcoming members','供后续成员阅读'):tr('Chat note','群聊备注')),m.text,false)]);
  for(const m of safeJSON(r.timeline,[])){
    if(['running','awaitingOwner','paused','blocked','stopped','stopping','accepted','changes'].includes(m.state))
      timeline.push([m.time,()=>entry(feed,'','TWOS',stamp(m.time),[message(m.state),message(m.reason)].filter(Boolean).join(' · '),false)])
  }
  timeline.sort((a,b)=>a[0]-b[0]).forEach(([,append])=>append());
  if(state.archived)p.append(node('p',tr('Saved conversation · status at the time of recording','历史群聊 · 显示记录时的状态'),'small'));
  if(r.reason)p.append(node('p',message(r.reason),'warning'));
  if(!state.archived)controls(p,r)
}
function controls(p,r) {
  const action=(cmd,extra={})=>send(cmd,{id:r.id,...extra}), a=actions(p);
  if(['running','paused'].includes(r.state))button(a,tr('Stop dispatches','停止派发'),()=>action('stop'));
  if(r.state==='paused'){
    const next=r.members.find(m=>m[0]===r.next);
    if(next && next[1]!=='Codex'){
      button(a,tr('Open ','打开 ')+next[1]+' · '+role(next[0]),()=>send('reviewer',{role:next[0]}));
      if(r.reason==='reviewerChanged')p.append(node('p',tr('Approved selection','已批准的选择')+' · '+next[1]+' · '+next[2],'small'))
    }
    button(a,tr('Reconcile and continue','核对并继续'),()=>action('resume'),true)
  }
  if(r.state==='blocked' && r.reason==='identity')button(a,tr('Check original model receipts','核对原模型回执'),()=>action('evidence')).disabled=state.notice==='reconciling';
  if(r.recoverMemberReply)button(a,tr('Check saved member reply','核对已存成员回复'),()=>action('recoverMemberReply'));
  if(r.unreadReview)button(a,tr('Check saved reviewer reply','核对已存审核回复'),()=>action('recheckReview'));
  if(r.pendingDecision)button(a,tr('Recheck saved decision','核对已记录决定'),()=>action('retryDecision'));
  if(r.state==='awaitingOwner' && !r.pendingDecision){
    if(!r.out)button(a,tr('Save delivery','保存交付'),()=>action('export'));
    field(p,'comment',tr('Revision notes','修改意见'));
    const decisions=actions(p);button(decisions,tr('Accept delivery','接受交付'),()=>action('accept'),true).disabled=!r.out;
    button(decisions,tr('Request changes','提出修改'),()=>action('changes',{comment:draft.comment})).disabled=!r.out
  }
  const c=node('div',null,'compose'), box=node('textarea'),label=node('label',tr('Message this group','写入群聊'));
  const canShare=['running','paused'].includes(r.state);
  box.id='team-message';label.htmlFor=box.id;box.rows=2;box.value=compose;
  c.append(label,box);const a2=actions(c);
  function post(share) {
    if(!box.value.trim())return;
    const key=pendingMessage?.text===box.value && pendingMessage.share===share?pendingMessage.key:crypto.randomUUID();
    pendingMessage={key,text:box.value,share};action('message',{key,text:box.value,share:share?'yes':'no'})
  }
  const save=button(a2,tr('Save note','保存备注'),()=>post(false));
  const share=canShare?button(a2,tr('Send to upcoming members','发送给后续成员'),()=>post(true),true):null;
  box.oninput=()=>{compose=box.value;save.disabled=!compose.trim();if(share)share.disabled=save.disabled};
  box.oninput();p.append(c)
}
function fact(parent,label,value){if(!value)return;const dl=node('dl');dl.append(node('dt',label),node('dd',value));parent.append(dl)}
function inspection(r){
  const aside=by('scope-info'),files=by('delivery-files');
  aside.replaceChildren();files.replaceChildren();files.hidden=!r;
  by('scope-title').textContent=r?tr('Task details','任务详情'):tr('Team setup','组队');
  if(!r){
    for(const name of roles){aside.append(person(name,serviceFor(name),chosen(name)));
      if(serviceFor(name)!=='Codex')button(aside,tr('Open ','打开 ')+serviceFor(name),()=>send('reviewer',{role:name}))}
    button(actions(aside),tr('Refresh models','刷新型号'),()=>send('refresh'));return
  }
  if(!following && !state.archived && r.state==='running')button(aside,tr('Follow active member','跟随当前成员'),()=>{following=true;renderLocal()});
  const a=r.chat.find(item=>item.id===selection);
  if(a){
    aside.append(person(a.role,a.service,a.requested),node('p',memberStatus(a),'status'));
    fact(aside,tr('Dispatched','派发时间'),stamp(a.started));fact(aside,tr('Completed','完成时间'),stamp(a.finished));
    fact(aside,tr('Transport receipt','通道回执'),a.dispatch==='accepted'?tr('Request received by the service','提供方已接收请求'):message(a.dispatch));
    if(a.observedSelection)fact(aside,tr('Web selection for this dispatch','本次派发的网页设置'),modelLabel(a.observedSelection));
    fact(aside,tr('Reported model','实际型号'),a.model||tr('Awaiting provider evidence','等待提供方证据'));
    const observed=safeJSON(a.activity,[]);
    if(observed.length){
      aside.append(node('h3',tr('Observed activity','已观察到的活动')));
      const list=node('ul');
      const names={generation:tr('Generating a reply','正在生成回复'),plan:tr('Plan update','计划更新'),agentMessage:tr('Progress update','进度说明'),commandExecution:tr('Command','执行命令'),fileChange:tr('File change','文件改动'),mcpToolCall:tr('Tool call','工具调用'),webSearch:tr('Search','搜索')};
      for(const item of observed)list.append(node('li',[names[item.kind]||item.kind,message(item.status),item.text].filter(Boolean).join(' · ')));
      aside.append(list)
    }
    aside.append(node('p',headline(a),'details-body'));
    if(a.verified!==undefined)fact(aside,tr('Independent data check','独立数据校验'),a.verified?tr('Passed','通过'):tr('Failed','未通过'));
    if(a.prompt){const d=node('details');d.append(node('summary',tr('Assigned instructions','本次指派内容')),node('pre',a.prompt));aside.append(d)}
    if(a.reply){const d=node('details');d.append(node('summary',tr('Full published reply','完整公开回复')),node('pre',a.reply));aside.append(d)}
    if(a.thread||a.resultHash){const d=node('details');d.append(node('summary',tr('Execution receipt','执行回执')));
      fact(d,tr('Conversation','会话'),a.thread);fact(d,tr('Turn','轮次'),a.turn);fact(d,'SHA-256',a.resultHash);aside.append(d)}
    if(!state.archived && a.service!=='Codex' && r.next===a.role)button(aside,tr('Open member conversation','打开成员会话'),()=>send('reviewer',{role:a.role}));
    if(!state.archived && state.notice==='approvalRequired')button(aside,tr('Review permission request','查看权限请求'),()=>send('codex'))
  } else if(selection==='roster'){
    for(const [name,s,m,n] of r.members){
      aside.append(person(name,s,r.memberSelections?.[name]||m,n));
      if(r.memberSelections?.[name] && r.memberSelections[name]!==m)fact(aside,tr('Originally approved','组队时的选择'),modelLabel(m));
      if(!state.archived && s!=='Codex')button(aside,tr('Open member settings','打开成员设置')+' · '+s,()=>send('reviewer',{role:name}))
    }
  }
  else{aside.append(node('p',r.goal),node('p',message(r.state),'status'))}
  files.append(node('h3',tr('Delivery & files','交付与文件')));
  fact(files,r.out?tr('Final location','最终路径'):tr('Chosen destination','选定交付位置'),r.out||r.folder);
  if(r.out){const links=actions(files);
    for(const file of ['dashboard.html','summary.md','review.md','delivery.json'])button(links,file,()=>send('reveal',{id:r.id,file}));
    button(files,tr('Show final files in Finder','在访达中查看最终文件'),()=>send('reveal',{id:r.id}))}
  else files.append(node('p',tr('Final delivery pending.','等待正式交付。'),'small'));
  const version=a?.version||r.version;
  if(version && version<=r.version){
    fact(files,tr('Reviewed snapshot · v','送审快照 · v')+version,r.workPath+'/TWOS-'+r.id+'-v'+version+'-frozen');
    const links=actions(files);
    for(const file of ['dashboard.html','summary.md'])button(links,file,()=>send('frozen',{id:r.id,version:String(version),file}))
  }
}
function renderLocal(){pageKey='';if(state)window.renderTeam(state)}
window.teamCSV=csv=>{draft.csv=csv;renderLocal()};
window.renderTeam=s=>{
  const prev=state;state=s;
  if(!prev && s.draft){
    for(const k of ['goal','csv'])if(typeof s.draft[k]==='string')draft[k]=s.draft[k];
    for(const name of roles){draft[name.toLowerCase()]=s.draft[name]||'';if(s.draft[name+'Name'])names[name]=s.draft[name+'Name']}
  }
  if(draft.goal===null || prev && prev.zh!==s.zh && draft.goal===sampleGoal(prev.zh))draft.goal=sampleGoal(s.zh);
  if(draft.csv===null)draft.csv=s.sample;
  for(const r of roles){const k=r.toLowerCase();if(s.catalog.length && !s.catalog.includes(draft[k]))draft[k]=s.catalog[0]}
  if(selectedRoom!==(s.run?.id||'')){if(selectedRoom)messageDrafts.set(selectedRoom,compose);selectedRoom=s.run?.id||'';selection='';following=true;compose=messageDrafts.get(selectedRoom)||'';pendingMessage=null;draft.comment=''}
  if(pendingMessage && safeJSON(s.run?.messages,[]).some(m=>m.id===pendingMessage.key)){if(compose===pendingMessage.text)compose='';pendingMessage=null}
  if(s.run && (following || !selection))selection=s.run.chat.at(-1)?.id || 'goal';
  const key=JSON.stringify(s);if(key===pageKey)return;pageKey=key;
  const focus=document.activeElement?.id,sel=document.activeElement?.selectionStart;
  const center=by('work'),sc= center.scrollTop,nearEnd=center.scrollHeight-center.clientHeight-sc<40;
  document.documentElement.lang=s.zh?'zh-CN':'en';library();
  const nav=by('nav');nav.replaceChildren();
  const toggle=(cls,word)=>{const b=button(nav,word,()=>{const show=!document.body.classList.contains(cls);document.body.classList.remove('show-library','show-detail');if(show)document.body.classList.add(cls)});b.className='mobile '+(cls==='show-library'?'history-toggle':'detail-toggle')};
  toggle('show-library',tr('Chats','群聊'));toggle('show-detail',tr('Details','详情'));
  if(s.archived && s.current)button(nav,tr('Current task','当前任务'),()=>send('current'));
  center.replaceChildren(node('h2',s.run?s.run.goal:s.proposal||preview?tr('Your team','本次团队'):tr('New team task','新建团队任务')));
  if(s.run){preview=false;chat(center,s.run)}else if(s.proposal)proposal(center,s.proposal);else if(preview)previewRoster(center);else form(center);
  inspection(s.run);by('notice').textContent=message(s.notice)||'';
  if(focus && focus!=='search'){const el=by(focus);if(el){el.focus({preventScroll:true});if(typeof sel==='number' && (el.tagName==='TEXTAREA' || el.type==='text'))el.setSelectionRange(sel,sel)}}
  if(prev?.run?.id===s.run?.id){center.scrollTop=nearEnd && prev?.run?.chat?.length!==s.run?.chat?.length?center.scrollHeight:sc}
};
function sampleGoal(zh){return zh?'按区域汇总销售额，制作双语离线报告并独立核对。':'Summarize sales by region in a bilingual offline report and independently check the figures.'}
