"""Owner-reported layout, Pack review and Guided action regressions."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tests import test_vol19_fresh_install_first_run_ui as layout

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'static_cockpit/vol12_static_mvp'
JS = (UI / 'twos_command_center.js').read_text()


def function(name):
    return re.search(r'^  (?:async )?function ' + name + r'\(.*?(?=^  (?:async )?function |\Z)', JS, re.M | re.S)[0]


def node(source):
    result = subprocess.run(['node', '-e', source], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout or '{}')


@pytest.mark.parametrize('width,zoom', [(1329, 1), (884, 1), (390, 1), (1329, 2), (390, 2)])
def test_shared_step_labels_do_not_wrap_or_overlap_headings(tmp_path, monkeypatch, width, zoom):
    original = layout._geometry_fixture

    def fixture(surface):
        page = original(surface).replace('</head>', f'<style>body {{ zoom: {zoom}; }}</style></head>')
        return page.replace('const result = {', '''
  const labels = visible.filter(el => el.matches('.step-label')).map(el => {
    const range = document.createRange(); range.selectNodeContents(el);
    const lines = Array.from(range.getClientRects()).filter(r => r.width > 0);
    const rect = el.getBoundingClientRect();
    const heading = el.parentElement.querySelector('strong, h2, h3');
    const head = heading && heading.getBoundingClientRect();
    const text = range.getBoundingClientRect();
    return {text: el.textContent, lines: lines.length,
      contained: text.top >= rect.top && text.bottom <= rect.bottom,
      noOverlap: !head || text.right <= head.left || text.left >= head.right
        || text.bottom <= head.top || text.top >= head.bottom};
  });
  const banner = document.querySelector('#first-run-first-task-banner');
  const paragraph = banner.querySelector('p');
  const descriptionFits = paragraph.scrollHeight <= paragraph.clientHeight
    && paragraph.getBoundingClientRect().bottom <= banner.getBoundingClientRect().bottom;
  const result = {labels, descriptionFits,''')

    monkeypatch.setattr(layout, '_geometry_fixture', fixture)
    for surface in ('setup', 'first_task'):
        result = layout._browser_geometry(tmp_path, surface=surface, width=width)
        assert result['labels']
        for label in result['labels']:
            assert label['lines'] == 1, label
            assert label['contained'] and label['noOverlap'], label
        if surface == 'first_task':
            assert any(label['text'] == 'Step 07 of 07' for label in result['labels'])
            assert result['descriptionFits']


def test_prepare_completion_reenables_review_without_reload_and_blocks_duplicate_prepare():
    output = node('''
const assert = require('assert/strict');
const AUTH_STATES = {SIGNED_IN: 'signed_in'};
const state = {auth: 'signed_in', pending: new Set(), firstDeliveryGuide: {
  task_id: 1, stage_index: 1, stage: 'Task Ready', stages: [],
  next_action: 'prepare', action_label: 'Prepare First Delivery'}};
const nodes = {};
function byId(id) { return nodes[id] ||= {textContent: '', disabled: false,
  setAttribute() {}, removeAttribute() {}, replaceChildren() {}}; }
function selectedTask() { return {id: 1}; }
function currentCodexRun() { return null; }
function setFeedback() {}
let calls = 0, finish;
async function api(path) {
  assert.equal(path, '/api/tasks/1/first-delivery/prepare'); calls++;
  return new Promise(resolve => { finish = () => resolve({id: 2}); });
}
async function refreshWorkspace() {
  Object.assign(state.firstDeliveryGuide, {stage_index: 2, stage: 'Pack Ready',
    next_action: 'review_pack', action_label: 'Review Instruction Pack'});
  renderWorkspace();
}
function renderWorkspace() { renderFirstDeliveryGuide(); }
''' + ''.join(function(name) for name in ('performAction', 'renderFirstDeliveryGuide', 'firstDeliveryAction')) + '''
(async () => {
  const pending = firstDeliveryAction();
  await firstDeliveryAction();
  assert.equal(calls, 1);
  assert.equal(byId('first-delivery-action').disabled, true);
  finish(); await pending;
  assert.equal(state.pending.size, 0);
  assert.equal(byId('first-delivery-action').disabled, false);
  assert.equal(byId('first-delivery-action').textContent, 'Review Instruction Pack');
  process.stdout.write(JSON.stringify({calls, enabled: !byId('first-delivery-action').disabled}));
})();
''')
    assert output == {'calls': 1, 'enabled': True}


def test_review_pack_is_read_only_task_scoped_and_displays_the_actual_frozen_pack():
    output = node('''
let task = {id: 1};
let pack = {id: 7, task_id: 1, version: 3, status: 'approved',
  development_task: 'first_delivery.txt only <script>untrusted</script>',
  content: 'exact persisted Pack content', generation_metadata: {guided_delivery: {configuration_id: 4}}};
let opened = 0, errors = 0;
const nodes = {};
function byId(id) { return nodes[id] ||= {showModal() {opened++;}}; }
function selectedTask() {return task;}
function currentPack() {return pack;}
function humanStatus(value) {return value;}
function setFeedback() {errors++;}
function api() {throw Error('Review must not mutate or execute');}
''' + function('reviewCurrentPack') + '''
reviewCurrentPack();
const reviewed = {...nodes['pack-review-content']};
task = {id: 2}; reviewCurrentPack();
pack = null; reviewCurrentPack();
process.stdout.write(JSON.stringify({opened, errors, reviewed,
  identity:nodes['pack-review-identity'].textContent}));
''')
    assert output['opened'] == 1 and output['errors'] == 2
    assert output['identity'] == 'Task #1 · Pack #7 · v3 · approved'
    assert 'first_delivery.txt only <script>untrusted</script>' in output['reviewed']['textContent']
    assert 'exact persisted Pack content' in output['reviewed']['textContent']
    assert '"configuration_id": 4' in output['reviewed']['textContent']
    page = (UI / 'twos_command_center.html').read_text()
    dialog = page.split('<dialog id="pack-review-dialog"', 1)[1].split('</dialog>', 1)[0]
    assert dialog.count('<button ') == 1 and '>Close</button>' in dialog
    assert '<button id="review-pack"' in page
    assert 'elements.reviewPack.addEventListener("click", reviewCurrentPack)' in JS


def test_prerequisite_shortcut_cannot_turn_into_execution_on_a_state_change():
    handler = JS.split('byId("run-prerequisite-action").addEventListener("click", function () {', 1)[1].split('\n    });', 1)[0]
    output = node('''
let calls = 0;
const state = {};
function firstDeliveryAction() { calls++; }
function click() {''' + handler + '''}
for (const next_action of ['start_run', 'apply', 'delivery', 'review_pack']) {
  state.firstDeliveryGuide = {next_action}; click();
}
const unsafeCalls = calls;
for (const next_action of ['tool_setup', 'prepare']) {
  state.firstDeliveryGuide = {next_action}; click();
}
process.stdout.write(JSON.stringify({unsafeCalls, safeCalls: calls}));
''')
    assert output == {'unsafeCalls': 0, 'safeCalls': 2}
    assert 'eligibility.eligible !== true' in function('renderActionAvailability')
    assert 'if (!task || !pack || !pack.approved || !eligibility || eligibility.eligible !== true)' in function('openCodexRunConfirmation')
