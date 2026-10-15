"""Actual Safari checks for public thinking summaries and empty error replies."""
import json
import pytest
from tests.test_vol20_2_workbench_ui import fixture, browser


def visibility_fixture(locale, case):
    page=fixture(locale)
    message={'id':'reply-1','role':'assistant','body':'','state':'RUNNING' if case=='summary' else 'FAILED','client':'/synthetic/old-codex','evidence':{'public_activity':[{'id':'connect','kind':'status','code':'CLI_RECONNECTING'}]} if case=='summary' else {'error_code':'PROVIDER_MODEL_UNAVAILABLE','requested_model':'gpt-6.1-sol','duration_seconds':118.22,'private_evidence':{'receipt_id':'fixture-diagnostic'}}}
    current={'id':'synthetic-chat','project_id':None,'title':'Visibility fixture','messages':[{'id':'user-1','role':'user','body':'Build a mobile checklist','state':'COMPLETED','evidence':{}},message],'handoffs':[],'deliveries':[],'attachments':[],'draft':'Keep my draft','draft_version':0,'draft_attachments':[],'draft_tool':{'source_ids':[],'search':''}}
    setup='current='+json.dumps(current,ensure_ascii=False)+";db.chats=[current];db.layout.chat_id=current.id;db.connection={tool_id:'synthetic-tool',model:'gpt-6.1-sol'};\n"
    page=page.replace('const copy=x=>',setup+'const copy=x=>',1)
    start=page.index('<script>\n(async()=>{')
    scenario=r'''
<script>
(async()=>{
const checks=[],$=id=>document.getElementById(id),zh=locale==='zh-CN'?1:0;
const assert=(x,m)=>{if(!x)throw Error(m);checks.push(m);};
const until=async(fn)=>{for(let i=0;i<350;i++){if(fn())return;await pause();}throw Error('timeout waiting for UI');};
const click=sel=>{const n=document.querySelector(sel);if(!n)throw Error('missing '+sel);n.click();};
try{
 await until(()=>$('messages').querySelector('[data-message="reply-1"]'));
 if(CASE==='summary'){
  assert($('messages').querySelector('.message-progress').textContent.includes(catalog['progress.CLI_RECONNECTING'][zh]),'waiting displays the actual connection state');
  assert(!$('messages').querySelector('.thinking,.message-reasoning'),'no three dots or invented thinking before a summary arrives');
  current.messages[1].evidence.public_activity.push({id:'summary-1',kind:'summary',text:'**Mobile layout**\nChecking touch targets.'});
  await until(()=>$('messages').querySelector('.message-reasoning .markdown strong'));
  assert($('messages').querySelector('.message-reasoning').open&&$('messages').textContent.includes('Checking touch targets.'),'public summary is readable and initially expanded during the response');
  click('.message-reasoning summary');
  current.messages[1].evidence.public_activity[1].text='**Mobile layout**\nChecking touch targets and saved progress.';
  await until(()=>$('messages').textContent.includes('saved progress.'));
  assert(!$('messages').querySelector('.message-reasoning').open,'stream updates preserve the reader’s collapsed summary');
  current.messages[1].state='COMPLETED';current.messages[1].body='Final response';
  await until(()=>$('messages').textContent.includes('Final response'));
  assert(!$('messages').querySelector('.message-progress')&&$('messages').querySelector('.message-reasoning'),'completion keeps the summary and stops the waiting status');
  click('.message-reasoning summary');assert($('messages').querySelector('.message-reasoning').open,'completed summary can be reopened');
 }else{
  assert($('messages').querySelector('.message-notice').textContent===catalog['error.PROVIDER_MODEL_UNAVAILABLE'][zh],'empty failed reply directly explains the model error');
  click('.message-evidence summary');
  assert($('messages').querySelector('.message-evidence').open&&$('messages').querySelector('.message-evidence dd').textContent==='PROVIDER_MODEL_UNAVAILABLE','message details are visible and expandable on an empty response');
  current.messages[1].evidence.duration_seconds=119;
  await until(()=>$('messages').querySelector('.message-evidence').textContent.includes('119'));
  assert($('messages').querySelector('.message-evidence').open&&$('messages').querySelector('.message-evidence').textContent.includes('/synthetic/old-codex'),'diagnostics stay expanded across polling and identify the client');
  click('[data-action=repair-connection]');await until(()=>$('dialog').open&&$('connect-form'));
  assert($('connect-tool').value==='synthetic-desktop'&&!$('connect-consent').checked&&sends===0,'repair suggests a desktop client without silently connecting or resending');
  assert(requests.filter(r=>r.url==='/api/r2/wb/connect').length===0,'connection repair requires the explicit existing-plan connection action');
  click('[data-action=close]');assert($('draft').value==='Keep my draft','opening connection settings preserves the draft');
  current.messages[1].evidence={};
  await until(()=>$('messages').querySelector('.message-evidence').textContent.includes(catalog.diagnosticUnavailable[zh]));
  assert($('messages').querySelector('.message-evidence summary'),'legacy failure without saved evidence still has details');
 }
 assert(document.documentElement.scrollWidth<=innerWidth+2,'no viewport horizontal overflow');
 window.parent.postMessage({twosGeometry:{checks,width:innerWidth,provider_calls:0,api:'SYNTHETIC',case:CASE}},'*');
}catch(e){window.parent.postMessage({twosGeometry:{error:e.message,checks,alerts:$('alerts').textContent}},'*');}
})();
</script>'''.replace('CASE',json.dumps(case))
    return page[:start]+scenario+'</body></html>'


@pytest.mark.parametrize('locale',['en-US','zh-CN'])
@pytest.mark.parametrize('width',[390,1280])
@pytest.mark.parametrize('case',['summary','failure'])
def test_discussion_visibility_in_actual_browser(tmp_path,monkeypatch,locale,width,case):
    monkeypatch.setattr(browser,'_geometry_fixture',lambda _:visibility_fixture(locale,case))
    result=browser._browser_geometry(tmp_path,surface='discussion-visibility',width=width)
    assert 'error' not in result,result
    assert result['width']==width and result['provider_calls']==0
    assert len(result['checks'])>=7
