from pathlib import Path
import json
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_owner_ui_uses_passive_reads_and_one_explicit_action_at_a_time():
    source = (ROOT/'static_cockpit/maintenance.js').read_text()
    harness = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
class Element {
 constructor(){this.value='';this.hidden=false;this.disabled=false;this.listeners={};this.children=[];this.textContent='';}
 addEventListener(name,callback){this.listeners[name]=callback;}
 replaceChildren(){this.children=[];}
 append(...children){this.children.push(...children);}
}
const nodes=new Map(), requests=[];
const get=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
const status={app_version:'0.17.0',schema:'vol19.005',target_schema:'vol19.005',backup_ready:true,
 recovery:{state:'NONE'},authority:{},sensitive_content_warning:'Sensitive TWOS content'};
const plan={kind:'RESTORE',plan_id:'plan-1',from_schema:'vol19.005',to_schema:'vol19.005',
 recovery_point:'/current/private/prior.sqlite3',counts:{tasks:1},confirmation:'RESTORE_TWOS',consequences:'Replace logical data; workspace files remain separate.'};
let releaseBackup;
async function fetch(url,options){
 requests.push({url,options});
 let value={};
 if(url.endsWith('/status'))value=status;
 if(url.endsWith('/data'))value={tasks:[{title:'Baseline',status:'queued'}]};
 if(url.endsWith('/backups')){await new Promise(resolve=>releaseBackup=resolve);value={backup:'/current/private/one.twos-backup',state:'BACKUP_COMPLETE'};}
 if(url.endsWith('/inspect'))value={integrity_status:'VERIFIED'};
 if(url.endsWith('/restore-plan'))value=plan;
 return {ok:true,json:async()=>value};
}
vm.runInNewContext(SOURCE,{document:{getElementById:get,createElement:()=>new Element()},fetch,console});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const click=async id=>{get(id).listeners.click();await tick();await tick();};
(async()=>{
 await tick();await tick();
 assert.equal(requests.filter(r=>r.options.method==='POST').length,0);
 assert.equal(get('primary').textContent,'Create Backup');
 await click('primary');
 assert.equal(get('primary').disabled,true);
 assert.equal(get('primary').textContent,'Working…');
 await click('primary');
 assert.equal(requests.filter(r=>r.url.endsWith('/backups')).length,1);
 releaseBackup();await tick();await tick();
 assert.equal(get('primary').textContent,'Inspect Backup');
 assert.equal(get('backup-path').value,'/current/private/one.twos-backup');
 await click('primary');
 assert.equal(get('primary').textContent,'Review Restore Plan');
 assert.equal(requests.filter(r=>r.url.endsWith('/confirm')).length,0);
 await click('primary');
 assert.equal(get('primary').textContent,'Approve Maintenance Plan');
 await click('primary');
 assert.equal(get('primary').textContent,'Confirm Restore');
 assert.equal(get('primary').disabled,true);
 get('confirmation').value='RESTORE_TWOS';get('confirmation').listeners.input();
 assert.equal(get('primary').disabled,false);
 await click('primary');
 assert.equal(requests.filter(r=>r.url.endsWith('/confirm')).length,1);
 assert.equal(get('login').hidden,false);
 assert.equal(requests.filter(r=>/codex|apply|push|local-commit/.test(r.url)).length,0);
 console.log('PASS');
})().catch(error=>{console.error(error);process.exitCode=1;});
'''.replace('SOURCE', json.dumps(source), 1)
    result = subprocess.run(['node','-e',harness],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    assert 'PASS' in result.stdout


@pytest.mark.parametrize('width',[1280,390])
def test_maintenance_real_browser_geometry_with_advanced_paths(tmp_path, monkeypatch, width):
    import tests.test_vol19_fresh_install_first_run_ui as layout
    original = layout._geometry_fixture('first_task')
    measurement = original[original.rfind('<script>'):original.rfind('</body>')]
    measurement = measurement.replace('"#task-card"','"main"')
    page = (ROOT/'static_cockpit/maintenance.html').read_text().replace('<script src="/maintenance.js"></script>','')
    page = page.replace('<section id="login">','<section id="login" hidden>').replace('<div id="maintenance" hidden>','<div id="maintenance">')
    page = page.replace('<details>','<details open>')
    long_path = '/current/authorized/' + 'long-directory-'*35 + '/backup.twos-backup/database.sqlite3'
    page = page.replace('<pre id="advanced"></pre>',f'<pre id="advanced">{long_path}\nsha256: '+ 'f'*64 + '</pre>')
    page = page.replace('<p id="next" aria-live="polite"></p>','<p id="next" aria-live="polite">Next action: Create Backup.</p>')
    page = page.replace('</body>',measurement+'</body>')
    monkeypatch.setattr(layout,'_geometry_fixture',lambda surface:page)
    result = layout._browser_geometry(tmp_path,surface='first_task',width=width)
    assert result['innerWidth']==width
    assert result['documentScrollWidth']<=width
    assert result['overflow']==[]
