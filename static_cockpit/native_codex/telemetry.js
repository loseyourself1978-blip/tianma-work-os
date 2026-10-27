/* Read-only observation surface. No execution, purchase or reset operations. */
(()=>{'use strict';
 let zh=false,last=null;const $=id=>document.getElementById(id),t=(en,cn)=>zh?cn:en;
 const post=action=>window.webkit?.messageHandlers?.twosCodex?.postMessage({action});
 const text=(id,value)=>$(id).textContent=value;
 const known=v=>v!==null&&v!==undefined&&Number.isFinite(Number(v));
 const number=v=>known(v)?Number(v).toLocaleString(zh?'zh-CN':'en-US',{maximumFractionDigits:6}):t('Unknown','未知');
 const date=v=>known(v)&&v>0?new Date(v*1000).toLocaleString(zh?'zh-CN':'en-US'):t('Not recorded','未记录');
 const duration=v=>{if(!known(v))return t('Start not yet confirmed','尚未确认开始');const n=Math.max(0,Math.floor(v));return n<60?n+t('s','秒'):n<3600?Math.floor(n/60)+t('m ','分 ')+n%60+t('s','秒'):Math.floor(n/3600)+t('h ','小时 ')+Math.floor(n%3600/60)+t('m','分');};
 function row(parent,label,value){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=String(value);parent.append(dt,dd);}
 function remaining(window){
  const field=Object.hasOwn(window,'remainingPercent')?'remainingPercent':'usedPercent',value=window[field];
  // Percent is a service unit, not a coerced token count, string or boolean.
  if(typeof value!=='number'||!Number.isFinite(value)||value<0||value>100)return null;
  if(field==='remainingPercent'&&Object.hasOwn(window,'usedPercent')&&
     (typeof window.usedPercent!=='number'||!Number.isFinite(window.usedPercent)||Math.abs(value+window.usedPercent-100)>0.000001))return null;
  return Number((field==='usedPercent'?100-value:value).toFixed(6));
 }
 function usageRing(parent,value,label,stale){
  const card=document.createElement('span');card.className='usage-ring-card';
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 64 64');svg.setAttribute('role','img');
  svg.setAttribute('aria-label',label+' · '+(value===null?t('Remaining unavailable','剩余额度暂不可用'):number(value)+t('% remaining','% 剩余'))+(stale?t(' · last known data',' · 上次数据'):''));
  const circle=className=>{const e=document.createElementNS(svg.namespaceURI,'circle');for(const [k,v]of Object.entries({cx:32,cy:32,r:27,fill:'none','stroke-width':5,'pathLength':100,'class':className}))e.setAttribute(k,v);svg.append(e);return e;};
  circle('ring-track');
  if(value!==null&&value>0){const arc=circle('ring-value');arc.setAttribute('transform','rotate(-90 32 32)');arc.setAttribute('stroke-linecap','butt');if(value<100)arc.setAttribute('stroke-dasharray',value+' '+(100-value));}
  const center=document.createElementNS(svg.namespaceURI,'text');center.setAttribute('x',32);center.setAttribute('y',36);center.setAttribute('text-anchor','middle');center.textContent=value===null?'—':number(value)+'%';if(center.textContent.length>6)center.setAttribute('class','ring-precise');svg.append(center);
  const caption=document.createElement('span');caption.className='ring-caption';caption.textContent=label;
  const status=document.createElement('span');status.className='ring-label';status.textContent=value===null?t('Unavailable','暂不可用'):t('Remaining','剩余');
  card.append(svg,status,caption);parent.append(card);
 }
 const states=()=>({running:t('Running','运行中'),tool:t('Tool running','工具执行中'),waiting_approval:t('Waiting for your approval','等待你的批准'),waiting_input:t('Waiting for your input','等待你的输入'),unverified:t('Connection / state needs verification','连接或状态待核验'),completed:t('Execution ended','执行已结束'),failed:t('Failed','失败'),interrupted:t('Stopped','已停止'),cancelled:t('Cancelled','已取消'),queued:t('Queued','排队中'),verification:t('Review in progress','复核进行中')});
 const reasons=()=>({terminal:t('Execution has ended; this is not Owner acceptance.','执行已结束，不代表 Owner 已验收。'),offline:t('Connection is unavailable or control is unverified.','连接不可用或控制状态未核验。'),waiting_user:t('Waiting for your action; the estimate is paused.','等待你的操作，估计暂停。'),stale_activity:t('No recent activity evidence; the tool may still be running. Refresh status.','近期没有新活动证据，工具可能仍在运行。可刷新状态。'),unknown_remaining_work:t('No countable remaining plan steps.','没有可计数的剩余计划步骤。'),insufficient_samples:t('At least two observed completed step durations are needed.','需要至少两项实际完成步骤的耗时样本。')});
 const errors=()=>({unsupported:t('Interface or authentication mode not supported','接口或认证方式不支持'),authentication:t('Authentication / access failed','认证或访问失败'),network:t('Network / connection failed','网络或连接失败'),capacity:t('Service capacity unavailable','服务容量暂不可用'),quota:t('Quota exhausted','配额耗尽'),rate_limit:t('Rate limited','请求速率受限'),unavailable:t('Data temporarily unavailable','数据暂不可用'),account_changed:t('Account changed; verifying current scope','账号已变更，正在核对范围')});
 function render(p){
  if(!p)return;last=p;
  text('usage-title',t('Usage & Limits','额度与用量'));text('usage-refresh',t('Refresh usage','刷新用量'));
  text('run-title',t('Run Activity','运行活动'));text('run-refresh',t('Refresh run status','刷新状态'));text('run-advanced-title',t('Timing and estimate details','计时与估计详情'));
  text('usage-cancel',t('Stop waiting for this refresh','停止等待本次刷新'));$('usage-cancel').hidden=!p.reading;
  $('usage-refresh').disabled=!p.connected||p.reading;$('run-refresh').disabled=!p.connected||!p.threadId;
  const account=$('usage-account');account.replaceChildren();
  row(account,t('Service / authentication','服务 / 认证'),'Codex · '+p.authentication);
  row(account,t('Plan returned by service','服务返回的计划'),p.plan==='unknown'?t('Unknown','未知'):p.plan);
  row(account,t('Scope','统计范围'),t('Account/workspace routed by this Codex connection. Not a sum of ChatGPT and Codex clients.','当前 Codex 连接所路由的账号/工作区；不把 ChatGPT 和多个 Codex 客户端相加。'));
  const limits=p.accountVerified?p.limits:null, buckets=limits?.rateLimitsByLimitId;
  // The legacy snapshot mirrors a bucket. Never add it to rateLimitsByLimitId.
  const entries=buckets&&Object.keys(buckets).length?Object.entries(buckets):limits?.rateLimits?[[limits.rateLimits.limitId||'default',limits.rateLimits]]:[];
  if(typeof limits?.ordinaryUsageAllowed==='boolean')row(account,t('Ordinary usage allowed by service','服务允许常规使用'),limits.ordinaryUsageAllowed?t('Yes','是'):t('No','否'));
  const windows=$('usage-windows');windows.replaceChildren();const compact=$('usage-compact');compact.replaceChildren();let windowCount=0;
  const stale=!!p.accountVerified&&p.limitsUpdated>0&&(!p.connected||p.now-p.limitsUpdated>300||!!p.errors?.limits||!!p.errors?.account);
  for(const [id,bucket] of entries){
   const block=document.createElement('section'),title=document.createElement('strong');title.textContent=bucket.limitName||id;block.append(title);
   const dl=document.createElement('dl');block.append(dl);
   for(const [key,window] of [['primary',bucket.primary],['secondary',bucket.secondary]])if(window){
    const name=known(window.windowDurationMins)?number(window.windowDurationMins)+t(' minute window',' 分钟窗口'):t('Window length not returned','未返回窗口长度');
    const value=remaining(window);windowCount++;
    row(dl,name,value===null?t('Unavailable: missing or invalid percentage.','暂不可用：百分比缺失或无效。'):number(value)+t('% remaining','% 剩余'));
    row(dl,t('Window identity','窗口标识'),id+' / '+key);
    row(dl,t('Service reset time','服务重置时间'),date(window.resetsAt));
    if(known(window.resetsAt)&&window.resetsAt<=p.now&&window.resetsAt>p.limitsUpdated)row(dl,t('Reset pending confirmation','重置待确认'),t('Waiting for a new service snapshot; not assumed reset.','等待服务新快照，尚未视为额度恢复。'));
    usageRing(compact,value,(bucket.limitName||id)+' · '+name+' · '+key,stale);
   }
   if(bucket.credits){const c=bucket.credits;row(dl,t('Credits balance (separate unit)','Credits 余额（独立单位）'),c.balance==null?t('Not returned','未返回'):c.balance);row(dl,t('Service credits flags','服务 Credits 标志'),t('has credits: ','有 Credits：')+(c.hasCredits===true?t('yes','是'):c.hasCredits===false?t('no','否'):t('unknown','未知'))+t('; unlimited: ','；无限：')+(c.unlimited===true?t('yes','是'):c.unlimited===false?t('no','否'):t('unknown','未知')));}
   if(bucket.rateLimitReachedType)row(dl,t('Limit reported','服务报告的限制'),bucket.rateLimitReachedType);
   if(bucket.individualLimit){const c=bucket.individualLimit;row(dl,t('Service spend-control values (unit not inferred)','服务消费控制数值（不推断单位）'),String(c.used)+' / '+String(c.limit)+' · '+number(c.remainingPercent)+t('% remaining','% 剩余'));row(dl,t('Spend-control reset time','消费控制重置时间'),date(c.resetsAt));}
   if(bucket.spendControlReached===true)row(dl,t('Spend control','消费控制'),t('Reached','已达到'));
   windows.append(block);
  }
  if(!entries.length)windows.textContent=p.accountVerified?t('No quota windows returned. This does not mean unlimited.','未返回额度窗口，不代表无限额度。'):t('Verifying account identity before showing saved values.','先核对账号身份，再显示缓存数值。');
  if(!windowCount)usageRing(compact,null,t('Account quota','账户额度'),stale);
  text('usage-reading',p.reading?t('Reading service data…','正在读取服务数据…'):stale?t('Last known data','上次数据'):'');
  text('usage-freshness',t('Source: account/rateLimits/read · updated ','来源：account/rateLimits/read · 更新于 ')+date(p.limitsUpdated)+(stale?t(' · stale / offline',' · 已过期或离线'):''));
  const tokens=$('usage-tokens');tokens.replaceChildren();
  row(tokens,t('Scope','范围'),t('This thread’s cumulative service snapshot; never added to account totals. “Last” is the last model request, not the entire task.','本线程服务累计快照，不与账号总量相加。“最近一次”指最近模型请求，不是整个任务。'));
  const names={inputTokens:t('Input','输入'),cachedInputTokens:t('Cached input (included in input)','缓存输入（包含于输入）'),cacheWriteInputTokens:t('Cache write input (subset)','缓存写入输入（子项）'),outputTokens:t('Output','输出'),reasoningOutputTokens:t('Reasoning output (included in output)','推理输出（包含于输出）'),totalTokens:t('Total tokens','总 Token')};
  for(const [key,label] of Object.entries(names))row(tokens,label,number(p.tokens?.total?.[key])+' / '+number(p.tokens?.last?.[key]));
  row(tokens,t('Snapshot updated','快照更新时间'),date(p.tokens?.updated));
  row(tokens,t('Locally observed turns / tool items','本地观测轮次 / 工具项'),number(p.observedTurns)+' / '+number(p.observedTools));
  row(tokens,t('Model request count','模型请求次数'),t('Unknown: token snapshots do not enumerate requests.','未知：Token 快照不枚举模型请求次数。'));
  row(tokens,t('Task tokens / cost','任务 Token / 费用'),t('Not independently attributed; no cost or remaining-run conversion.','未独立归属；不换算费用或剩余可运行次数。'));
  const daily=$('usage-history');daily.replaceChildren();
  const summary=p.accountVerified?p.usage?.summary:null;
  row(daily,t('Service lifetime tokens','服务累计 Token'),number(summary?.lifetimeTokens));
  row(daily,t('Source / last updated','来源 / 更新时间'),'account/usage/read · '+date(p.usageUpdated));
  for(const day of (p.accountVerified?p.usage?.dailyUsageBuckets||[]:[]).slice().sort((a,b)=>a.startDate.localeCompare(b.startDate)).slice(-7))row(daily,day.startDate,number(day.tokens)+t(' tokens',' Token'));
  text('usage-error',Object.entries(p.errors||{}).map(([key,value])=>key+': '+(errors()[value]||value)).join(' · ')+(p.saveError?t(' · Observation metadata could not be saved.',' · 观测元数据未能保存。'):''));
  const queue=p.queued,run=queue?null:p.run;
  text('elapsed-label',t('Elapsed','已运行'));text('eta-label',t('Estimated remaining','预估剩余'));text('work-label',t('Work remaining','剩余工作量'));
  text('run-elapsed',run?duration(run.elapsed):t('Not started','尚未开始'));
  text('run-eta-value',t('Cannot estimate yet','暂无法估计'));text('run-work',t('Cannot estimate yet','暂无法估计'));
  text('run-scope',t('Current execution only, including its own checks; not project progress or Owner acceptance.','仅当前执行及其执行中的检查，不代表整个项目或 Owner 验收。'));
  if(queue){text('run-compact',t('Queued / awaiting start · submitted ','排队或等待开始 · 提交于 ')+date(queue.submitted));}
  else if(run){text('run-compact',(states()[run.state]||run.state)+' · '+duration(run.elapsed));}
  else text('run-compact',t('No observed run in this conversation','本会话暂无已观测运行'));
  const detail=$('run-detail');detail.replaceChildren();
  if(run){
   row(detail,t('Submitted / actual start','提交 / 实际开始'),date(run.submitted)+' / '+date(run.started));
   row(detail,t('Since submission / before confirmed start (wall timestamps)','提交后总经过 / 确认开始前（墙钟时间戳）'),duration(run.wallTimes?.sinceSubmission)+' / '+duration(run.wallTimes?.beforeStart));
   row(detail,t('Observed elapsed time (monotonic; service duration when returned)','已观测经过时间（单调计时；服务有返回时采用服务耗时）'),duration(run.elapsed));
   row(detail,t('Observed active / waiting time','已观测活跃 / 等待时间'),duration(run.observedActive)+' / '+duration(run.observedWait));
   row(detail,t('Offline intervals','离线区间'),run.offlineUnknown?t('Contains intervals not observed; not counted as active.','存在未观测区间，不计入活跃时间。'):t('None recorded','未记录'));
   row(detail,t('Last activity','最近活动'),date(run.lastActivity));
   row(detail,t('Plan steps','计划步骤'),run.planTotal?number(run.planDone)+' / '+number(run.planTotal)+t(' completed; plan revisions: ',' 项已完成；计划修订：')+number(run.planRevisions):t('No step total returned; no percentage inferred.','服务未返回步骤总数，不推算百分比。'));
   const work=run.workload;
   if(work?.available&&typeof work.remainingPercent==='number'){
    text('run-work',number(work.remainingPercent)+'%'+(work.basis==='execution_ended'?'':t(' (estimate)','（估算）'))+(work.stale?t(' · last known',' · 上次数据'):''));
    row(detail,t('Work estimate basis','工作量估计依据'),work.basis==='execution_ended'?t('This execution ended; business checks and acceptance remain separate.','本次执行已结束；业务检查及验收另行记录。'):t('Equal plan items, not a time ratio. In-progress items remain unfinished.','按计划项等权估计，不等同时间比例；进行中的项仍计为未完成。'));
    row(detail,t('Plan version / updated','计划版本 / 更新时间'),number(work.planVersion)+' / '+date(work.updated));
   }else row(detail,t('Work estimate unavailable','工作量暂无法估计'),work?.reason==='invalid_plan_status'?t('Unrecognized plan status; no percentage inferred.','计划状态无法识别，不推算百分比。'):t('No complete structured plan returned for this execution.','本次执行未返回完整结构化计划。'));
   row(detail,t('Requested / returned model','请求 / 实际返回模型'),(run.requestedModel==='unknown'?t('Unknown','未知'):run.requestedModel)+' / '+(run.returnedModel==='unknown'?t('Not returned','未返回'):run.returnedModel));
   row(detail,t('Result return / business result','结果回传 / 业务结果'),(({not_recorded:t('Not recorded / not linked to a discussion','未记录／未关联原讨论'),confirmed:t('Returned to discussion','已回到原讨论'),pending:t('Waiting to return','等待回传'),sending:t('Returning result','正在回传'),unknown:t('Return needs verification','回传待核验')})[run.returnState]||run.returnState)+' / '+(({partial:t('Partially completed','部分完成'),blocked:t('Blocked','受阻'),failed:t('Failed','失败'),unverified:t('Not verified','未验证'),not_completed:t('Not completed','尚未完成'),reported_pass:t('Reported pass; not Owner acceptance','报告通过；非 Owner 接受'),pass:t('Reported pass; not Owner acceptance','报告通过；非 Owner 接受')})[run.businessResult]||run.businessResult));
   const eta=run.eta;
   if(eta.available){text('run-eta-value',t('About ','约 ')+duration(eta.low)+'–'+duration(eta.high));text('run-eta',t('TWOS estimate: ','TWOS 本地估计：')+duration(eta.low)+'–'+duration(eta.high));row(detail,t('Estimate basis','估计依据'),t('Observed completed plan steps · samples: ','已观测计划步骤耗时 · 样本数：')+eta.samples+' · '+t('confidence: ','可信程度：')+(eta.confidence==='low'?t('low','低'):eta.confidence==='moderate'?t('moderate','中等'):eta.confidence)+' · '+date(eta.updated)+(eta.reassessed?t(' · reassessed after overrun',' · 超时后已重新评估'):''));}
   else {text('run-eta',t('No reliable ETA: ','暂无法可靠估计：')+(reasons()[eta.reason]||({invalid_plan_status:t('Unknown plan status.','计划状态未知。'),heterogeneous_samples:t('Observed step durations differ too much for a reliable range.','已观测步骤耗时差异过大，无法可靠推算。')})[eta.reason]||eta.reason));if(eta.reason==='waiting_user')text('run-eta-value',t('Waiting for you','等待你的操作'));if(eta.reason==='offline'||eta.reason==='stale_activity')text('run-eta-value',t('Estimate paused','估计暂停'));if(eta.reason==='terminal')text('run-eta-value',t('Execution ended','执行已结束'));}
  }else text('run-eta',t('Start not yet confirmed. A new message is not sent by refreshing status.','尚未确认开始。刷新状态不会发送新消息。'));
 }
 window.twosTelemetry={receive:render,language:value=>{zh=value;render(last)},selectThread:id=>{if(last?.threadId!==id)render({...last,threadId:id,run:null,queued:null,tokens:null,observedTurns:null,observedTools:null});}};
 $('usage-cancel').onclick=()=>post('cancelUsage');$('usage-refresh').onclick=()=>post('usage');$('run-refresh').onclick=()=>post('runStatus');
 render({now:Date.now()/1000,authentication:'unknown',plan:'unknown',errors:{}});
})();
