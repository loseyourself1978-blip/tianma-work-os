"""Exercise the shipped render functions; no browser/provider or user state."""
import json
from pathlib import Path
import re
import subprocess


def test_locale_switch_localizes_accessible_navigation_and_team_evidence():
    root = Path(__file__).resolve().parents[1] / 'static_cockpit/project_first'
    source = (root / 'app.js').read_text()
    catalog = json.loads((root / 'catalog.json').read_text())

    def function(name):
        return re.search(r'^ function ' + name + r'\(.*?(?=^ (?:async )?function |\Z)',
                         source, re.M | re.S)[0]

    harness = r'''
'use strict';
const assert=require('node:assert/strict');
const node={attributes:{},innerHTML:'',setAttribute(k,v){this.attributes[k]=v;}};
const $=()=>node,E=v=>String(v??'');
let locale='en-US',view='home',auth={authenticated:true};
const projects=[{id:17,name:'User-authored 中文 content'}];
const project={id:17,executions:[],activity:[]};
const fetch=()=>{throw Error('Rendering must not call a provider or API');};
const work={id:'work_fixed',revision:4,kind:'document',title:'Canonical task',
 body:'Keep this 原文',state:'COMPLETED',output_locale:'zh-CN',sources:[],
 plan_hash:'exact_approved_hash',plan:{model:'configured-model',
 team_mode:'MULTIPLE_MODELS_CONFIGURED_NOT_VERIFIED'}};
const original=JSON.stringify(work);
'''
    checks = r'''
for(const lang of ['en-US','zh-CN','en-US']){
 locale=lang;nav();
 assert.equal(node.attributes['aria-label'],lang==='zh-CN'?'我的项目':'My projects');
 assert(node.innerHTML.includes('User-authored 中文 content'));
 const html=workView(work),current=html.split('<details>')[0];
 assert(current.includes(lang==='zh-CN'?'这不代表各角色已执行或通过复核':'not proof that every role has executed'));
 assert(!current.includes('MULTIPLE_MODELS_CONFIGURED_NOT_VERIFIED'));
 assert(html.includes('MULTIPLE_MODELS_CONFIGURED_NOT_VERIFIED'),'Audit retains canonical state');
 assert.equal(JSON.stringify(work),original,'Rendering cannot rewrite plan/content/approval hash');
}
for(const lang of ['en-US','zh-CN']){
 locale=lang;
 const single={...work,plan:{...work.plan,team_mode:'SINGLE_MODEL_MULTI_ROLE'}};
 assert(workView(single).includes(lang==='zh-CN'?'不代表独立模型验证':'not independent-model validation'));
 const unknown={...work,plan:{...work.plan,team_mode:'FUTURE_UNATTESTED_STATE'}};
 assert(workView(unknown).includes(lang==='zh-CN'?'团队执行方式尚未核验':'Team execution mode is not verified'));
}
console.log(JSON.stringify({passed:true}));
'''
    script = harness + 'const catalog=' + json.dumps(catalog, ensure_ascii=False) + ';\n'
    script += '\n'.join(function(n) for n in ('t', 'button', 'nav', 'workView', 'historyView'))
    result = subprocess.run(['node', '-e', script + checks], capture_output=True, text=True,
                            timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['passed']


def test_open_source_dialog_and_error_switch_in_place_without_rewriting_content():
    """Execute shipped source dispatch + locale listener against a minimal DOM.

    Real modal layout/focus is additionally checked in the final packaged GUI.
    """
    root=Path(__file__).resolve().parents[1]/'static_cockpit/project_first'
    source=(root/'app.js').read_text();catalog=json.loads((root/'catalog.json').read_text())
    dispatch=re.search(r"  if\(action==='source'\).*?return;}\n",source)[0]
    listener=re.search(r" document.addEventListener\('change',e=>\{if\(\['language'.*?\);\n",source)[0]
    localize=source[source.index(' function localize('):source.index(' function button(')]
    guarded=re.search(r" async function guarded.*?\n",source)[0]
    script=r'''
const assert=require('node:assert/strict');
let locale='en-US',epoch=0,busy=false,handler,sourceBody='',hash='',renders=0,draft='untouched';
const project={id:3},data={name:'User-authored 中文',sha256:'immutable-source-hash',content:'Original business text 原文'};
const original=JSON.stringify(data),work={revision:4,plan_hash:'approved-fixed',output_locale:'zh-CN'};
const t=k=>catalog[k][locale],E=String;
const nodes={'dialog':{open:false},'dialog-language':{id:'dialog-language',value:'en-US',focus(){document.activeElement=this;}},'dialog-error':{innerHTML:''}};
let translated=[];
const $=id=>nodes[id];
nodes.dialog.querySelectorAll=selector=>selector==='[data-i18n]'?translated:[];
const document={activeElement:nodes['dialog-language'],addEventListener(k,fn){handler=fn;},querySelectorAll(){return translated;}};
function saveDrafts(){assert.equal(draft,'untouched');}
function render(){renders++;}
function notify(){throw Error('unexpected locale error');}
function clearNotice(){}
async function api(path,body){if(path.endsWith('/preferences')){assert(['en-US','zh-CN'].includes(body.locale));return {};};assert(path.endsWith('/sources/source_1'));return data;}
function openDialog(title,html,kind){
 assert.equal(kind,'source');nodes.dialog.open=true;sourceBody=data.content;hash=data.sha256;
 translated=[...html.matchAll(/data-i18n="([^"]+)">([^<]*)/g)].map(m=>({dataset:{i18n:m[1]},textContent:m[2]}));
 assert(translated.some(n=>n.dataset.i18n==='originalContent'));
}
'''
    checks=r'''
(async()=>{
 await dispatch('source',{dataset:{id:'source_1'}});
 const originalNode=translated[0];
 for(const next of ['zh-CN','en-US']){
  handler({target:{id:'dialog-language',value:next}});await localeQueue;
  assert(nodes.dialog.open);assert.equal(translated[0],originalNode);
  assert.equal(originalNode.textContent,catalog.originalContent[next]);
  assert.equal(sourceBody,data.content);assert.equal(hash,data.sha256);
  assert.equal(JSON.stringify(data),original);assert.equal(work.plan_hash,'approved-fixed');
  assert.equal(work.output_locale,'zh-CN');assert.equal(draft,'untouched');
  assert.equal(document.activeElement,nodes['dialog-language']);
 }
 await guarded(async()=>{throw {code:'SOURCE_CHANGED'};});
 assert(nodes['dialog-error'].innerHTML.includes('data-i18n="error.SOURCE_CHANGED"'));
 console.log('PASS');
})();
'''
    script='const catalog='+json.dumps(catalog,ensure_ascii=False)+';\n'+script
    script+='async function dispatch(action,el){'+dispatch+'}\n'+localize+guarded+listener+checks
    result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='PASS'


def test_all_product_modal_copy_and_attributes_switch_without_rebuilding_controls():
    """Execute common localization against mounted nodes, including async inserts.

    Scope lists real dialog instructions; original/source text is deliberately
    outside the localization attributes. Packaged GUI evidence covers layout.
    """
    root=Path(__file__).resolve().parents[1]/'static_cockpit/project_first'
    source=(root/'app.js').read_text();catalog=json.loads((root/'catalog.json').read_text())
    common=source[source.index(' function localize('):source.index(' function button(')]
    script=r'''
const assert=require('node:assert/strict');
let locale='en-US',focusCount=0,providerCalls=0;
const keys=['importTitle','importDesc','importBoundary','chooseFile','previewImport','manifest','safe','reference','excluded','importReason.TEXT_DATA_ONLY','originalContent','taskTitle','taskBody','bodyHelp','outputLanguage','selectSources','privacy','saveTask','targetScope','candidateScope','guiInstallInstructions','installedMatched','installPending','ownerAcceptanceSeparate','revisionCallNotice','error.IMPORT_SELECTION_REQUIRED','error.EVIDENCE_WRITE_FAILED','budgetWarning','cancel','close'];
const labels=keys.map(k=>({dataset:{i18n:k},textContent:catalog[k]['en-US']}));
const attrNodes=['placeholder','aria-label','title'].map(attr=>({attrs:{['data-i18n-'+attr]:'language'},getAttribute(k){return this.attrs[k]},setAttribute(k,v){this.attrs[k]=v}}));
const fixed={original:'Do not translate 原文',hash:'abc123',approval:'unchanged',task:19,selected:['source_3'],output_locale:'zh-CN'};
const before=JSON.stringify(fixed);
const modal={open:true,querySelectorAll(selector){if(selector==='[data-i18n]')return labels;return attrNodes.filter(n=>n.getAttribute(selector.slice(1,-1)));}};
const nodes={'dialog':modal,'dialog-language':{value:'en-US',focus(){focusCount++}},'language':{value:'en-US'}};
const document={activeElement:{id:'dialog-language'}};
const $=id=>nodes[id],t=k=>catalog[k][locale];
function saveDrafts(){}
function render(){}
function notify(){throw Error('unexpected failure');}
const persisted=[];
async function api(path,data){assert.equal(path,'/api/r2/preferences');persisted.push(data.locale);return {};}
'''
    checks=r'''
(async()=>{
 for(const next of ['zh-CN','en-US']){
  await changeLocale(next);
  assert(modal.open);
  for(const n of labels)assert.equal(n.textContent,catalog[n.dataset.i18n][next]);
  for(let i=0;i<3;i++)assert.equal(attrNodes[i].attrs[['placeholder','aria-label','title'][i]],catalog.language[next]);
  assert.equal(JSON.stringify(fixed),before);
 }
 // Concurrent selections serialize persistence as well as display.
 const a=changeLocale('zh-CN'),b=changeLocale('en-US');await Promise.all([a,b]);
 assert.equal(locale,'en-US');assert.equal(persisted.at(-1),'en-US');
 // A delayed preview render joins the existing localization mechanism.
 const delayed={dataset:{i18n:'importReason.TEXT_DATA_ONLY'},textContent:'stale'};
 labels.push(delayed);localize(modal);
 assert.equal(delayed.textContent,catalog[delayed.dataset.i18n]['en-US']);
 assert.equal(providerCalls,0);assert.equal(JSON.stringify(fixed),before);
 console.log('PASS');
})();
'''
    result=subprocess.run(['node','-e','const catalog='+json.dumps(catalog,ensure_ascii=False)+';'+script+common+checks],text=True,capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='PASS'
    # No modal transition may remove the common title/language/close shell.
    assert "$('dialog').innerHTML=" not in source.split('function openDialog')[0]
    assert 'data-i18n="importBoundary"' in source
