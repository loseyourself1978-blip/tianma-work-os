'use strict';
(() => {
 const $=id=>document.getElementById(id), esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const post=(action,extra={})=>window.webkit.messageHandlers.twosCodex.postMessage({action,...extra});
 let zh=false, connected=false, busy=false, desktop=false, uncertain=false, historyReady=false, resultAvailable=false, selected='', savedThread='', draftTimer, lastFinal='', source='', items=new Map();
 const t=(en,cn)=>zh?cn:en;
 function showNotice(text,detail=''){
  $('notice-text').textContent=text;$('notice-detail').textContent=detail;$('notice-details').hidden=!detail;$('notice').hidden=false;
 }
 const markdown=x=>window.twosMarkdown(String(x??''));
 const summaryText=x=>(Array.isArray(x)?x:[]).map(v=>typeof v==='string'?v:v.text||'').join('\n');
 function labels(){
  $('binding').textContent=t('Local conversation · official protocol','本机会话 · 官方协议连接');$('connect').textContent=t('Connect local Codex','连接本机 Codex');
  $('workspace').textContent=t('Open workspace','打开工作目录');$('more-threads').textContent=t('More','更多会话');$('reconnect').textContent=t('Reconnect and inspect','重新连接并查看');$('details-label').textContent=t('Details','消息详情');
  $('thread-label').textContent=t('Conversation','会话');$('empty')&&($('empty').textContent=t('Connect to choose an existing local conversation. Selecting a conversation does not execute it.','连接后选择已有本机会话。选择会话不会开始执行。'));
  $('draft').placeholder=t('Continue in this Codex conversation…','在此 Codex 会话中继续…');$('stop').textContent=t('Stop','停止');$('send').textContent=t('Send to Codex','交付 Codex 执行');
  $('more').textContent=t('Older messages','更早消息');$('return').textContent=t('Return result to discussion','将结果带回原讨论');
  for(const [id,label] of [['threads',t('Choose existing conversation','选择已有会话')],['model',t('Keep conversation model','沿用会话模型')]]){const empty=Array.from($(id).options).find(x=>!x.value);if(empty)empty.textContent=label;}
  updateControls();
 }
 function updateControls(){
  $('send').disabled=!connected||!selected||!historyReady||busy||uncertain||!$('draft').value.trim();$('threads').disabled=busy;$('model').disabled=busy;$('connect').hidden=connected;$('connect').disabled=busy;$('refresh').disabled=busy;$('reconnect').hidden=!uncertain;$('stop').hidden=!busy||uncertain;$('return').hidden=!resultAvailable;
  $('draft').disabled=busy;$('workspace').hidden=!selected;
  $('status').textContent=busy?t('Codex is working…','Codex 正在执行…'):desktop&&selected?t('History view · quit the Codex App before continuing here','历史视图 · 接续执行前请退出 Codex App'):'';
 }
 function renderItem(item,prepend=false){
  if(!item?.id)return;items.set(item.id,item);
  let node=document.getElementById('item-'+item.id), fresh=!node;
  if(fresh){node=document.createElement('article');node.id='item-'+item.id;node.className='message';}
  const open=node.querySelector('details')?.open;
  if(item.type==='userMessage'){node.className='message user';node.textContent=(item.content||[]).filter(x=>x.type==='text').map(x=>x.text).join('\n');}
  else if(item.type==='agentMessage'){
   node.innerHTML=markdown(item.text||'');
  }else if(item.type==='reasoning'){
   const text=summaryText(item.summary);if(!text)return;
   node.innerHTML='<details><summary>'+t('Thinking summary','思考摘要')+'</summary>'+markdown(text)+'</details>';
  }else if(item.type==='commandExecution'){
   const command=item.command||t('Command','命令'), brief=command.split('\n')[0];
   node.innerHTML='<details><summary>'+esc(brief.length>110?brief.slice(0,110)+'…':brief)+'</summary><pre>'+esc(command)+'</pre><pre>'+esc(item.aggregatedOutput||'')+'</pre>'+(item.exitCode===undefined?'':'<p>'+t('Exit code: ','退出码：')+esc(item.exitCode)+'</p>')+'</details>';
  }else if(item.type==='fileChange'){
   node.innerHTML='<details><summary>'+t('File changes','文件改动')+'</summary>'+(item.changes||[]).map(c=>'<p>'+esc(c.path)+'</p><pre>'+esc(c.diff||'')+'</pre>').join('')+'</details>';
  }else if(item.type==='plan'){node.innerHTML=markdown(item.text||'');}
  else return;
  if(node.querySelector('details'))node.querySelector('details').open=open===undefined?(item.type==='reasoning'&&busy):open;
  if(fresh){$('empty')?.remove();prepend?$('timeline').prepend(node):$('timeline').append(node);}
 }
 function approval(p){
  const box=document.createElement('section');box.className='approval';box.dataset.key=p.key;
  const params=p.params||{};
  if(p.method==='item/tool/requestUserInput'){
   box.innerHTML=(params.questions||[]).map(q=>'<label>'+esc(q.question||q.header||'')+'<textarea data-question="'+esc(q.id)+'"></textarea></label>').join('')+'<button data-submit>'+t('Reply','回复')+'</button>';
   box.querySelector('[data-submit]').onclick=()=>{const answers={};box.querySelectorAll('[data-question]').forEach(el=>answers[el.dataset.question]=[el.value]);post('answer',{key:p.key,answers});};
  }else if(p.method==='item/permissions/requestApproval'){
   box.innerHTML='<p>'+t('This request expands the current workspace permissions. This connection keeps its project boundary.','此请求会扩大当前工作区权限；此连接保留已有项目边界。')+'</p><p>'+esc(params.reason||'')+'</p><button data-reject>'+t('Reject and continue','拒绝并继续')+'</button>';
   box.querySelector('[data-reject]').onclick=()=>post('answer',{key:p.key,accept:false});
  }else{
   box.innerHTML='<p>'+esc(params.reason||t('Codex requests your decision.','Codex 请求你的决定。'))+'</p><pre>'+esc(params.command||params.grantRoot||'')+'</pre><button data-approve>'+t('Approve','批准')+'</button><button data-reject>'+t('Reject','拒绝')+'</button>';
   box.querySelector('[data-approve]').onclick=()=>post('answer',{key:p.key,accept:true});box.querySelector('[data-reject]').onclick=()=>post('answer',{key:p.key,accept:false});
  }
  $('approvals').append(box);
 }
 window.twosReceive=({kind,payload:p})=>{
  if(kind==='locale'){zh=p.zh;labels();}
  else if(kind==='control'){connected=p.connected;busy=p.busy;uncertain=!!p.uncertain;historyReady=!!p.historyReady;desktop=p.desktopRunning;selected=p.threadId||'';updateControls();}
  else if(kind==='notice')showNotice(p.text+(p.code?' ('+p.code+')':''),p.detail||'');
  else if(kind==='result'){resultAvailable=!!p.available;updateControls();}
  else if(kind==='clearApprovals')$('approvals').replaceChildren();
  else if(kind==='threads'){
   const prior=$('threads').value; $('threads').replaceChildren(new Option(t('Choose existing conversation','选择已有会话'),''));
   for(const row of p.items||[])$('threads').add(new Option(row.name||row.preview||row.id,row.id));
   if(selected&&!Array.from($('threads').options).some(o=>o.value===selected))$('threads').add(new Option(selected,selected));
   $('threads').value=selected||prior||savedThread;$('more-threads').hidden=!p.more;
   if(!selected&&savedThread&&$('threads').value===savedThread){post('select',{id:savedThread});savedThread='';}
  }else if(kind==='models'){
   const old=$('model').value;$('model').replaceChildren(new Option(t('Keep conversation model','沿用会话模型'),''));
   for(const row of p.items||[])$('model').add(new Option(row.displayName||row.model,row.model));$('model').value=old;
  }else if(kind==='thread'){
   selected=p.thread.id;if(!Array.from($('threads').options).some(o=>o.value===selected))$('threads').add(new Option(p.thread.name||p.thread.preview||selected,selected));$('threads').value=selected;$('cwd').textContent=p.thread.cwd||'';$('model').value=p.thread.model||'';
   $('timeline').replaceChildren();items.clear();lastFinal='';resultAvailable=false;$('return').hidden=true;updateControls();
  }else if(kind==='history'){
   const turns=[...(p.turns||[])].reverse();const prior=[];
   if(p.older){prior.push(...$('timeline').children);$('timeline').replaceChildren();}
   for(const turn of turns)for(const item of turn.items||[])renderItem(item);
   if(p.older)for(const item of prior){document.getElementById(item.id)?.remove();$('timeline').append(item);}
   else $('timeline').scrollTop=$('timeline').scrollHeight;
   $('more').hidden=!p.more;
  }else if(kind==='draft'){
   $('draft').value=p.text||'';source=p.source||'';savedThread=p.savedThread||savedThread;$('source').hidden=!source;$('source').textContent=source?t('From: ','来自：')+source:'';updateControls();
  }else if(kind==='sent'){
   $('draft').value='';$('approvals').replaceChildren();$('notice').hidden=true;updateControls();
  }else if(kind==='approval')approval(p);
  else if(kind==='answered')document.querySelector('.approval[data-key="'+CSS.escape(p.key)+'"]')?.remove();
  else if(kind==='summary')renderItem({id:p.id,type:'reasoning',summary:p.summary});
  else if(kind==='turnCompleted'){
   $('approvals').replaceChildren();$('status').textContent=p.status==='completed'?t('Finished','已完成'):p.status==='interrupted'?t('Stopped · conversation saved','已停止 · 会话已保存'):t('Not completed · inspect the latest output','未完成 · 请查看最近输出');
   if(p.status==='completed')$('notice').hidden=true;
   if(p.error)showNotice(t('The response did not finish.','回复未能完成。'),p.error.message||String(p.error));
  }else if(kind==='event'){
   const e=p.params||{};
   const nearEnd=$('timeline').scrollHeight-$('timeline').scrollTop-$('timeline').clientHeight<100;
   if(p.method==='item/started'||p.method==='item/completed')renderItem(e.item);
   else if(p.method==='item/agentMessage/delta'){
    const item=items.get(e.itemId)||{id:e.itemId,type:'agentMessage',text:''};item.text+=(e.delta||'');renderItem(item);
   }else if(p.method==='item/commandExecution/outputDelta'){
    const item=items.get(e.itemId)||{id:e.itemId,type:'commandExecution',command:''};item.aggregatedOutput=(item.aggregatedOutput||'')+(e.delta||'');renderItem(item);
   }else if(p.method==='item/reasoning/summaryTextDelta'){
    const item=items.get(e.itemId)||{id:e.itemId,type:'reasoning',summary:['']};const i=e.summaryIndex||0;item.summary[i]=(item.summary[i]||'')+(e.delta||'');renderItem(item);
   }else if(p.method==='turn/plan/updated'){
    renderItem({id:'plan-'+e.turnId,type:'plan',text:(e.plan||[]).map(x=>'- '+x.step).join('\n')});
   }else if(p.method==='turn/diff/updated')renderItem({id:'diff-'+e.turnId,type:'fileChange',changes:[{path:t('Current diff','当前差异'),diff:e.diff||''}]});
   else if(p.method==='error')showNotice(e.willRetry?t('Codex is reconnecting…','Codex 正在重新连接…'):t('Codex reported an error. This request was not restarted automatically.','Codex 返回了错误，本请求没有自动重新执行。'),e.error?.message||e.message||'');
   if(nearEnd)$('timeline').scrollTop=$('timeline').scrollHeight;
  }
 };
 $('connect').onclick=()=>post('connect');$('reconnect').onclick=()=>post('reconnect');$('more-threads').onclick=()=>post('moreThreads');$('refresh').onclick=()=>post('refresh');$('threads').onchange=()=>{clearTimeout(draftTimer);post('draft',{text:$('draft').value});post('select',{id:$('threads').value});};
 $('workspace').onclick=()=>post('workspace');$('more').onclick=()=>post('more');$('return').onclick=()=>post('return');$('stop').onclick=()=>post('interrupt');
 $('draft').addEventListener('input',()=>{updateControls();clearTimeout(draftTimer);draftTimer=setTimeout(()=>post('draft',{text:$('draft').value}),180);});
 $('draft').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();if(!$('send').disabled)$('composer').requestSubmit();}});
 $('composer').onsubmit=e=>{e.preventDefault();if($('send').disabled)return;clearTimeout(draftTimer);post('draft',{text:$('draft').value});post('send',{text:$('draft').value,model:$('model').value});};
 labels();post('ready');
})();
