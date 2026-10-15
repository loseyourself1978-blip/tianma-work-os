(async()=>{
 const result={passed:false,surfaces:[],locale_checks:0,cancel_event_checks:0,provider_calls:0,
               innerWidth,innerHeight,phase:'bootstrap'};
 const assert=(condition,message)=>{if(!condition)throw Error(message);};
 let phase=result.phase;Object.defineProperty(result,'phase',{enumerable:true,get:()=>phase,set:value=>{phase=value;parent.postMessage({twosCheckpoint:value},'*');}});
 // Yield to browser tasks, not background-tab timers. Safari throttles timer
 // polls when the automation client occludes the window; deadlines stay 10s.
 const tick=()=>new Promise(resolve=>{const channel=new MessageChannel();channel.port1.onmessage=()=>{channel.port1.close();channel.port2.close();resolve();};channel.port2.postMessage(null);});
 const wait=async fn=>{for(let i=0;i<150;i++){if(fn())return;await tick();}throw Error('UI_STATE_NOT_REACHED:'+result.phase);};
 const find=selector=>{const el=document.querySelector(selector);assert(el,'CONTROL_MISSING:'+selector);return el;};
 const visible=el=>{const r=el.getBoundingClientRect(),style=getComputedStyle(el);
  assert(style.visibility==='visible'&&style.display!=='none'&&r.width>=24&&r.height>=24,'CONTROL_NOT_VISIBLE');
  assert(r.left>=0&&r.top>=0&&r.right<=innerWidth+1&&r.bottom<=innerHeight+1,'CONTROL_OUTSIDE_VIEWPORT');
  const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);
  assert(hit===el||el.contains(hit),'CONTROL_OBSCURED');return r;};
 const click=async selector=>{const el=find(selector);parent.postMessage({twosCheckpoint:result.phase+':click:'+selector},'*');el.scrollIntoView({block:'center'});visible(el);el.focus();el.click();await tick();return el;};
 const modal=()=>find('#dialog');
 const open=async action=>{
  if(action==='import'||action==='source')await click('[data-action="tab"][data-tab="sources"]');
  if(action==='new-task')await click('[data-action="tab"][data-tab="tasks"]');
  const selector='[data-action="'+action+'"]';await click(selector);await wait(()=>modal().open);return selector;
 };
 const closeControl=()=>{
  const el=find('#dialog [data-action="close"]'),r=visible(el),d=modal().getBoundingClientRect();
  assert(r.width>=40&&r.height>=40,'CLOSE_HIT_TARGET_TOO_SMALL');
  assert(r.left-d.left<=24&&r.top-d.top<=24,'CLOSE_NOT_AT_TOP_LEFT_CORNER');
  assert(el.getAttribute('aria-label')===fixtureCatalog.close[fixtureLocale],'CLOSE_ACCESSIBLE_NAME');
  return el;
 };
 try{
  await wait(()=>document.querySelector('[data-action="project"][data-id="901"]'));
  await click('[data-action="project"][data-id="901"]');
  await wait(()=>document.querySelector('[data-action="tab"]'));
  for(const action of ['import','source','new-task','edit-project','guide','identity']){
   result.phase=action;const opener=await open(action);closeControl();
   if(action==='new-task'){
    find('#task-title').value='Unsaved synthetic draft 原文';
    find('#task-body').value='Preserve without submitting';
    find('#output-locale').value='zh-CN';find('#input-source_fixture').checked=true;
   }
   for(const lang of ['en-US','zh-CN','en-US']){
    result.phase=action+':'+lang;
    const select=find('#dialog-language');select.value=lang;select.dispatchEvent(new Event('change',{bubbles:true}));
    await wait(()=>fixtureLocale===lang&&find('#dialog [data-action="close"]').getAttribute('aria-label')===fixtureCatalog.close[lang]);
    await tick();assert(modal().open,'LOCALE_CLOSED_DIALOG');
    assert(JSON.stringify(fixtureProject)===fixtureBefore,'BUSINESS_CONTENT_CHANGED');
    closeControl();modal().scrollTop=modal().scrollHeight;await tick();closeControl();
    if(action==='source')assert(find('pre.document').textContent===fixtureContent,'SOURCE_CHANGED');
    if(action==='new-task'){
     assert(find('#task-title').value==='Unsaved synthetic draft 原文','DRAFT_LOST');
     assert(find('#output-locale').value==='zh-CN'&&find('#input-source_fixture').checked,'SELECTION_CHANGED');
    }
    result.locale_checks++;
   }
   if(action==='import'){
    await click('[data-action="import-preview"]');
    await wait(()=>find('#dialog-error').textContent.includes('IMPORT_SELECTION_REQUIRED'));
    assert(modal().open,'ERROR_UNEXPECTEDLY_CLOSED_DIALOG');closeControl();
   }
   const close=closeControl();close.focus();close.click();close.click();await wait(()=>!modal().open);await tick();
   assert(document.activeElement===find(opener),'FOCUS_NOT_RETURNED_TO_OPENER');
   await open(action);
   if(action==='new-task')assert(find('#task-title').value==='Unsaved synthetic draft 原文','REOPEN_LOST_DRAFT');
   assert(typeof modal().requestClose==='function','NATIVE_CANCEL_API_UNAVAILABLE');
   modal().requestClose();await wait(()=>!modal().open);await tick();
   assert(document.activeElement===find(opener),'CANCEL_FOCUS_NOT_RETURNED');
   result.cancel_event_checks++;result.surfaces.push(action);
  }
  result.business_mutations=fixtureRequests.filter(r=>r.method!=='GET'&&r.path!=='/api/r2/preferences');
  assert(result.business_mutations.length===0,'UNEXPECTED_BUSINESS_REQUEST');
  assert(JSON.stringify(fixtureProject)===fixtureBefore,'FIXTURE_RECORD_CHANGED');
  result.passed=true;result.phase='COMPLETE';
 }catch(error){result.error=String(error.message);result.activeElement=document.activeElement?.outerHTML?.slice(0,400);}
 result.measuredAt=Date.now();parent.postMessage({twosGeometry:result},'*');
})();
