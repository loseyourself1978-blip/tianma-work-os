"""Real-browser modal interactions against unmodified shipped JS/CSS.

Only HTTP responses are synthetic. No Owner database, provider, approval or
execution is used. Native Escape is additionally exercised in packaged GUI QA;
requestClose below tests the browser's cancel-event path, not a fake keypress.
"""
import html
import json
from pathlib import Path

import pytest

import test_vol19_fresh_install_first_run_ui as browser


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'static_cockpit/project_first'


def _fixture():
    page = (ASSETS / 'index.html').read_text()
    catalog = json.loads((ASSETS / 'catalog.json').read_text())
    backend = r'''
const fixtureProject={id:901,name:'Isolated dialog test 原文',goal:'No business actions',kind:'blank',
 sources:[{id:'source_fixture',name:'Synthetic.txt',sha256:'fixed-source-hash',created_at:'2026-10-01'}],
 works:[],executions:[],activity:[],configuration_saved:false};
const fixtureBefore=JSON.stringify(fixtureProject),fixtureRequests=[];
const fixtureContent='Original source 原文\n'+('A long synthetic line for scrolling.\n'.repeat(100));
let fixtureLocale='en-US';
window.fetch=async(path,options={})=>{
 const method=options.method||'GET';fixtureRequests.push({path,method});let value;
 if(path.includes('/catalog.json'))value=fixtureCatalog;
 else if(path==='/api/r2/preferences'){
  if(method==='POST')fixtureLocale=JSON.parse(options.body).locale;
  value={locale:fixtureLocale};
 }else{
  if(method!=='GET')throw Error('UNEXPECTED_MUTATION:'+path);
  const responses={
   '/api/auth/status':{authenticated:true,owner_initialized:true,owner:{id:901}},
   '/api/setup/status':{enabled:true,state:'complete'},
   '/api/health':{version:'test',build:{build_version:'fixture'},installation_id:'isolated-dialog-fixture'},
   '/api/r2/projects':[fixtureProject],'/api/r2/projects/901':fixtureProject,
   '/api/r2/tools':{candidates:[],models:[]},
   '/api/r2/projects/901/sources/source_fixture':{name:'Synthetic.txt',sha256:'fixed-source-hash',content:fixtureContent}
  };value=responses[path];if(value===undefined)throw Error('UNEXPECTED_REQUEST:'+path);
 }
 return {ok:true,json:async()=>JSON.parse(JSON.stringify(value))};
};
'''
    page = page.replace('<link rel="stylesheet" href="/static_cockpit/project_first/styles.css?hash=BUILD">',
                        '<style>' + (ASSETS / 'styles.css').read_text() + '</style>')
    page = page.replace('<script src="/static_cockpit/project_first/app.js?hash=BUILD" defer></script>', '')
    scripts = ('<script>const fixtureCatalog=' + json.dumps(catalog, ensure_ascii=False) + ';' + backend + '</script>'
               '<script>' + (ASSETS / 'app.js').read_text() + '</script>'
               '<script>' + (ROOT / 'tests/fixtures/r2_dialog_controls.js').read_text() + '</script>')
    page = page.replace('</body>', scripts + '</body>')
    # A realistic height matters: the older width-only geometry harness uses a
    # 20,000px iframe and cannot prove that a close control survives scrolling.
    return ('<!doctype html><meta charset="utf-8"><style>body{margin:0}</style>'
            '<script>addEventListener("message",e=>{if(e.source===document.querySelector("iframe").contentWindow'
            '&&(e.data.twosGeometry||e.data.twosCheckpoint))parent.postMessage(e.data,"*");});</script>'
            '<iframe style="border:0;width:100%;height:720px" srcdoc="' + html.escape(page, quote=True) + '"></iframe>')


@pytest.mark.parametrize('width', [1280, 390])
def test_modal_close_corner_scroll_locale_cancel_and_focus_in_real_browser(tmp_path, monkeypatch, width):
    monkeypatch.setattr(browser, '_geometry_fixture', lambda _: _fixture())
    result = browser._browser_geometry(tmp_path, surface='r2-dialog-controls', width=width)
    assert result.get('passed'), result
    assert result['innerWidth'] == width and result['innerHeight'] == 720
    assert result['surfaces'] == ['import', 'source', 'new-task', 'edit-project', 'guide', 'identity']
    assert result['locale_checks'] == 18
    assert result['cancel_event_checks'] == 6
    assert result['business_mutations'] == []
    assert result['provider_calls'] == 0
