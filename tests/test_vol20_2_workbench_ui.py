"""Production UI in a real browser, with explicitly synthetic API responses.

Uses the existing actual-Safari bridge for the main gate. No model/mail calls.
"""
import json
from pathlib import Path
import pytest
from tests import test_vol19_fresh_install_first_run_ui as browser

ROOT=Path(__file__).resolve().parents[1]/'static_cockpit/workbench'


def fixture(locale):
    page=(ROOT/'index.html').read_text().replace('<link rel="stylesheet" href="/static_cockpit/workbench/styles.css?BUILD">','<style>'+(ROOT/'styles.css').read_text()+'</style>')
    page=page.replace('<script src="/static_cockpit/workbench/markdown.js?BUILD" defer></script>', '<script>'+(ROOT/'markdown.js').read_text()+'</script>')
    page=page.replace('src="/static_cockpit/workbench/app.js?BUILD" defer','')
    page=page.replace('<script src="/static_cockpit/workbench/delivery.js?BUILD" defer></script>', '<script>'+(ROOT/'delivery.js').read_text()+'</script>')
    mock=r'''
<script>
const catalog=CATALOG, locale=LOCALE;
let db={user:{id:1,name:'Synthetic account'},chats:[],layout:{},connection:null}, projects=[], current=null, sends=0, assigns=0, requests=[];
const copy=x=>JSON.parse(JSON.stringify(x)), pause=()=>new Promise(r=>setTimeout(r,20));
window.fetch=async(url,opt={})=>{
 const body=opt.body?JSON.parse(opt.body):null;requests.push({url,body});let value={};
 if(url.includes('catalog.json'))value=catalog;
 else if(url==='/api/auth/session')value={authenticated:true};
 else if(url==='/api/auth/email/status')value={configured:false};
 else if(url==='/api/r2/preferences')value={locale};
 else if(url==='/api/r2/wb/state')value=db;
 else if(url==='/api/r2/projects')value=projects;
 else if(url==='/api/r2/projects/1')value=projects[0];
 else if(url==='/api/r2/tools')value={candidates:[{id:'synthetic-tool',path:'/synthetic/codex'},{id:'synthetic-desktop',path:'/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'}],models:['gpt-5.6-luna','gpt-5.6-sol','gpt-5.6-terra','gpt-6-astra','gpt-6-luna','gpt-6-sol','gpt-6.1-sol','synthetic-model']};
 else if(url==='/api/r2/wb/layout')db.layout=body;
 else if(url==='/api/r2/wb/connect'){db.connection={model:body.model};value=db.connection;}
 else if(url==='/api/r2/wb/projects'){projects.push({id:1,name:body.name,kind:body.kind,target:{},sources:[],works:[],executions:[],team:{},integrated:{team:{},workspace:{}},deliveries:[],request_budget:{limit:null}});value={id:1};}
 else if(url==='/api/r2/wb/chats'){current={id:'synthetic-chat',project_id:null,title:'',messages:[],handoffs:[],deliveries:[],attachments:[],draft:'',draft_version:0,draft_attachments:[],draft_tool:{source_ids:[],search:''}};db.chats=[current];value={id:current.id};}
 else if(url==='/api/r2/wb/chats/synthetic-chat')value=current;
 else if(url.endsWith('/configuration')){projects[0].integrated.team=body;}
 else if(url.endsWith('/setup')){const d=current.deliveries[0];d.configuration.setup_done.push(body.step);if(body.step==='project'){d.project_id=1;current.project_id=1;}if(body.step==='team'){projects[0].integrated.team={planner:db.connection.model,executor:db.connection.model,reviewer:db.connection.model};Object.assign(d.configuration,projects[0].integrated.team);}if(body.step==='workspace'){projects[0].integrated.workspace={path:'/synthetic/private-project'};d.configuration.workspace='/synthetic/private-project';d.state='READY';}value=d;}
 else if(url.endsWith('/decide')){const d=current.deliveries[0];d.state='WAITING_APPROVAL';d.thread_id='fixture-thread';d.turn_id='fixture-turn';d.events.push({id:1,kind:'item/completed',payload:{phase:'execution',item:{id:'status',type:'agentMessage',text:'Inspecting the project files.'}}},{id:2,kind:'approval',payload:{request_id:12,method:'item/commandExecution/requestApproval',params:{threadId:d.thread_id,turnId:d.turn_id,command:'python3 project_test.py',reason:'Run the local project test',cwd:'/synthetic/private-project'}}});value={state:d.state};}
 else if(url.endsWith('/respond')){const d=current.deliveries[0];d.events.push({id:3,kind:'approval_answered',payload:{event_id:2,decision:body.decision}},{id:4,kind:'item/completed',payload:{phase:'execution',item:{id:'command',type:'commandExecution',command:'python3 project_test.py',exitCode:0,aggregatedOutput:'Fixture checks passed'}}},{id:5,kind:'item/completed',payload:{phase:'review',item:{id:'review',type:'agentMessage',text:'Reviewed the fixture result. [Source](/synthetic/private-project/main.py) [Outside](/synthetic/private-project/secret.txt)'}}});d.events.push({id:7,kind:'artifacts',payload:{files:[{path:'main.py',bytes:8}]}});d.state='COMPLETED';value={accepted:true};}
 else if(url.endsWith('/delete')){db.deleted_chats=[current];db.chats=[];}
 else if(url.endsWith('/restore')){db.chats=[current];db.deleted_chats=[];}
 else if(url.endsWith('/draft')){if(body.version!==current.draft_version)throw Error('fixture detected stale draft');current.draft=body.body;current.draft_attachments=body.attachments;current.draft_tool={source_ids:body.source_ids,search:body.search};value={version:++current.draft_version};}
 else if(url.endsWith('/assign')){assigns++;current.project_id=body.project_id;}
 else if(url.endsWith('/send')){sends++;await pause();current.messages.push({id:'user-1',role:'user',body:body.body,state:'COMPLETED',evidence:{}},{id:'reply-1',role:'assistant',body:'Synthetic contextual response',state:'COMPLETED',evidence:{}});current.title=body.body;current.draft='';current.draft_version++;value={id:'reply-1'};}
 else throw Error('Unimplemented synthetic endpoint '+url);
 return {ok:true,status:200,json:async()=>copy(value)};
};
</script>'''.replace('CATALOG',json.dumps(json.loads((ROOT/'catalog.json').read_text()),ensure_ascii=False)).replace('LOCALE',json.dumps(locale))
    scenario=r'''
<script>
(async()=>{
 const checks=[], $=id=>document.getElementById(id), guidedFields=[];
 document.addEventListener('focusin',e=>{if(e.target.id?.startsWith('integrated-'))guidedFields.push(e.target.id);});
 const assert=(x,m)=>{if(!x)throw Error(m);checks.push(m);};
 const until=async(fn)=>{for(let i=0;i<350;i++){if(fn())return;await pause();}throw Error('timeout waiting for UI');};
 const click=sel=>{const n=document.querySelector(sel);if(!n)throw Error('missing '+sel);n.click();};
 try{
  await until(()=>$('model-state').textContent.length>0);
  assert(db.chats.length===0&&projects.length===0,'zero project and chat on initial home');
  assert(getComputedStyle(document.querySelector('.right')).display==='none','home has no execution pane');
  assert($('welcome').textContent.includes(catalog.slogan[locale==='zh-CN'?1:0]),'exact localized slogan');
  $('draft').value='Original multiline idea\n中文输入保留';$('draft').dispatchEvent(new Event('input',{bubbles:true}));
  await until(()=>current?.draft.includes('中文输入保留'));
  $('draft').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',isComposing:true,bubbles:true}));
  $('draft').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',shiftKey:true,bubbles:true}));
  await pause();assert(sends===0,'IME and Shift Enter do not send');
  $('draft').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));
  await until(()=>$('connect-form'));
  assert(current.draft===$('draft').value&&sends===0,'unconnected send keeps draft and opens explicit connection');
  assert($('connect-model').tagName==='SELECT'&&$('connect-model').options[0].value==='gpt-6.1-sol','discussion uses a native dropdown with 6.1 first');
  $('connect-model').value='synthetic-model';$('connect-consent').checked=true;$('connect-form').requestSubmit();
  await until(()=>!$('dialog').open);
  assert($('draft').value.includes('中文输入保留'),'return from connection preserves original draft');
  click('[data-action=send]');click('[data-action=send]');
  await until(()=>$('messages').textContent.includes('Synthetic contextual response'));
  assert(sends===1&&current.messages.length===2,'double click sends exactly one request');
  const formatted='### Preparation\n**Important**\n- [ ] Passport\n- [x] Ticket\n\n1. First\n2. Second\n\n> Quote\n\n```html\n<img src=x onerror=alert(1)>\n```\n\n[Unsafe](javascript:alert) ![Image](https://example.test/private) <script>alert(1)<'+ '/script>\n\n| Item | Count |\n| --- | --- |\n| Bag | 1 |';
  const probe=document.createElement('div');probe.innerHTML=window.twosMarkdown(formatted);
  assert(probe.querySelector('h3')?.textContent==='Preparation'&&probe.querySelector('strong')?.textContent==='Important','Markdown headings and emphasis render');
  assert(probe.querySelectorAll('input[type=checkbox]').length===2&&probe.querySelectorAll('ol li').length===2&&probe.querySelector('table'),'Markdown tasks, numbered lists and tables render');
  assert(probe.querySelector('pre code').textContent.includes('<img')&&!probe.querySelector('img,script,a'),'untrusted HTML, remote images and unsafe links remain inert');
  const identifiers=document.createElement('div');identifiers.innerHTML=window.twosMarkdown('DEVELOPMENT_PROJECT_REQUIRED file__name__suffix test_empty_guidance.py _italic_ __bold__');
  assert(identifiers.textContent==='DEVELOPMENT_PROJECT_REQUIRED file__name__suffix test_empty_guidance.py italic bold'&&identifiers.querySelectorAll('em').length===1&&identifiers.querySelectorAll('strong').length===1,'Markdown preserves identifier underscores while rendering delimited emphasis');
  assert(!$('messages').querySelector('.who')&&!$('messages').textContent.includes('COMPLETED'),'chat has no visible role or lifecycle labels');
  click('[data-action=save-project]');await until(()=>$('project-form'));
  $('project-title').value='Synthetic project';$('project-form').requestSubmit();
  await until(()=>current.project_id===1&&!$('dialog').open&&!$('workspace').classList.contains('home-layout'));
  assert(sends===1&&assigns===1&&current.id==='synthetic-chat','save to project retains chat without replay');
  current.deliveries=[{id:'fixture-delivery',source_message_id:'reply-1',state:'PROPOSED',approval_hash:'fixture-hash',specification:{title:'Mobile checklist',objective:'Build a usable checklist.',deliverables:['index.html'],checks:['Add and toggle items']},configuration:{setup_done:[]},events:[]}];
  await until(()=>document.querySelector('[data-action=delivery-approve]:not([disabled])'));
  assert(['planner','executor','reviewer'].every(role=>guidedFields.includes('integrated-'+role)),'configuration actually visits and focuses all three model settings');
  assert(current.deliveries[0].state==='READY'&&projects[0].integrated.workspace.path==='/synthetic/private-project','automatic setup saves team and environment before handoff');
  assert(requests.filter(r=>r.url.endsWith('/setup')).map(r=>r.body.step).join(',')==='project,team,workspace','visible configuration follows ordered real setup requests');
  assert(!document.querySelector('[data-action=start],[data-action=approve],[data-action=plan],[data-action=review]'),'no manual preparation approval start review chain');
  const messageNode=$('messages').firstElementChild;
  click('[data-action=delivery-approve]');
  await until(()=>document.querySelector('[data-action=delivery-answer]'));
  assert(requests.filter(r=>r.url.endsWith('/decide')).length===1&&$('right-body').textContent.includes('Inspecting the project files.'),'one handoff starts and displays actual adapter events');
  const comment=$('decision-comment-2');comment.value='Keep all work in this project';
  current.deliveries[0].events.push({id:6,kind:'item/completed',payload:{phase:'execution',item:{id:'notice',type:'agentMessage',text:'Waiting for your decision.'}}});
  await until(()=>$('right-body').textContent.includes('Waiting for your decision.'));
  assert($('decision-comment-2').value==='Keep all work in this project','stream updates preserve approval comments');
  click('[data-action=delivery-answer][data-decision=approve]');
  await until(()=>$('right-body').textContent.includes('Reviewed the fixture result.'));
  assert(!document.querySelector('[data-action=delivery-answer]')&&!$('right-body').textContent.includes('approval_hash'),'resolved decisions disappear and normal timeline contains no JSON');
  assert($('right-body').querySelector('a[href$="/download"]'),'source-only delivery exposes download without requiring a previewable artifact');
  assert($('right-body').querySelector('.codex-message a[href$="/files/main.py"]')&&!$('right-body').querySelector('a[href*="secret.txt"]'),'Codex artifact links resolve through owned snapshots while unknown local paths remain inert');
  assert(requests.find(r=>r.url.endsWith('/respond')).body.comment==='Keep all work in this project','inline decision forwards the user comment');
  assert($('messages').firstElementChild===messageNode,'unchanged messages retain their DOM during streaming');
  $('draft').value='Do not lose this draft';$('draft').dispatchEvent(new Event('input',{bubbles:true}));
  for(const name of ['overview','sources','team','tasks','deliverables']){
   click(`[data-action=tab][data-tab=${name}]`);await until(()=>!$('detail').hidden);
   if(name==='team'){
    assert(['planner','executor','reviewer'].every(role=>$('integrated-'+role).tagName==='SELECT'&&$('integrated-'+role).options[0].value==='gpt-6.1-sol'),'all team roles use real model dropdowns with 6.1 first');
    $('integrated-executor').value='gpt-6.1-sol';$('integrated-team-form').requestSubmit();await until(()=>projects[0].integrated.team.executor==='gpt-6.1-sol');
    assert(!$('limit')&&!$('budget-limit')&&$('integrated-workspace'),'team has provider quotas and saved working environment without a TWOS call cap');
    await until(()=>$('detail').querySelector('[data-action=back]'));
   }
   click('[data-action=back]');await until(()=>$('detail').hidden);
   assert($('draft').value==='Do not lose this draft','draft survives '+name+' return');
  }
  click('[data-action=pane][data-pane=right]');await pause();assert($('workspace').classList.contains('hide-right'),'execution pane collapses');
  click('[data-action=pane][data-pane=right]');await pause();
  const oldWidth=getComputedStyle($('workspace')).getPropertyValue('--left');
  document.querySelector('[data-resize=left]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
  assert(getComputedStyle($('workspace')).getPropertyValue('--left')!==oldWidth,'keyboard pane resizing works');
  click('[data-action=chat-menu]');await until(()=>document.querySelector('[data-action=delete-chat]'));click('[data-action=delete-chat]');await until(()=>document.querySelector('[data-action=confirm-delete-chat]'));click('[data-action=confirm-delete-chat]');await until(()=>!db.chats.length&&!$('dialog').open);
  assert(current.draft==='Do not lose this draft','deleting preserves saved draft');
  click('[data-action=account]');await until(()=>document.querySelector('[data-action=deleted-chats]'));click('[data-action=deleted-chats]');await until(()=>document.querySelector('[data-action=restore-chat]'));click('[data-action=restore-chat]');await until(()=>db.chats.length===1&&document.querySelector('[data-action=chat]')&&!document.querySelector('[data-action=restore-chat]'));click('[data-action=close]');click('[data-action=chat]');await until(()=>$('draft').value==='Do not lose this draft');
  assert(sends===1&&current.messages.length===2,'delete and restore preserve messages without replay');
  const result={checks,sends,assigns,width:innerWidth,scrollWidth:document.documentElement.scrollWidth,api:'SYNTHETIC',provider_calls:0};
  assert(result.scrollWidth<=innerWidth+2,'no viewport horizontal overflow');
  window.parent.postMessage({twosGeometry:result},'*');
 }catch(e){window.parent.postMessage({twosGeometry:{error:e.message,checks,alerts:$('alerts').textContent,requests:requests.map(r=>r.url)}},'*');}
})();
</script>'''
    return page.replace('</body>',mock+'<script>'+(ROOT/'app.js').read_text()+'</script>'+scenario+'</body>')


@pytest.mark.parametrize('locale',['en-US','zh-CN'])
@pytest.mark.parametrize('width',[390,1280])
def test_workbench_interaction_and_geometry(tmp_path,monkeypatch,locale,width):
    monkeypatch.setattr(browser,'_geometry_fixture',lambda _:fixture(locale))
    result=browser._browser_geometry(tmp_path,surface='workbench',width=width)
    assert 'error' not in result,result
    assert result['width']==width and result['provider_calls']==0
    assert result['sends']==result['assigns']==1
    assert len(result['checks'])>=14
