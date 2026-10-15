"""Offline protocol regressions: no real CLI/provider is invoked."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading

import pytest

from twos_runtime.execution_evidence import EventStream, ExecutionFailure
from twos_runtime.project_execution import codex_document

MODEL = 'gpt-6.1-sol'
WARNING = {'type': 'item.completed', 'item': {'id': 'item_0', 'type': 'error',
    'message': f'Model metadata for `{MODEL}` not found. Defaulting to fallback metadata; this can degrade performance and cause issues.'}}


def offline_cli(tmp_path, case='valid'):
    """A synthetic process replays the observed protocol shape, not a model."""
    pre = [{'type': 'thread.started', 'thread_id': 'offline-metadata'}, WARNING,
           {'type': 'turn.started'}]
    end = [{'type': 'item.completed', 'item': {'id': 'item_1', 'type': 'agent_message', 'text': 'offline result'}},
           {'type': 'turn.completed'}]
    exit_code = 0
    final = 'offline result\n'
    if case == 'wrong_model':
        pre = copy.deepcopy(pre); pre[1]['item']['message'] = pre[1]['item']['message'].replace(MODEL, 'another-model')
    elif case == 'after_start': pre = [pre[0], pre[2], pre[1]]
    elif case == 'terminal_error': end += [{'type': 'error', 'message': 'synthetic provider failure'}]
    elif case == 'failed_turn': end[-1] = {'type': 'turn.failed', 'error': {'message': 'synthetic provider failure'}}
    elif case == 'nonzero': exit_code = 7
    elif case == 'mismatch': final = 'other response'
    elif case == 'no_terminal': end = end[:-1]
    elif case == 'conflicting_terminal': end += [{'type': 'turn.completed'}]
    elif case == 'refusal': end[0]['item'] = {'id': 'item_1', 'type': 'refusal'}
    elif case == 'duplicate_item': end[0]['item']['id'] = 'item_0'
    exe = tmp_path / 'offline-cli'
    exe.write_text('#!' + sys.executable + '\nimport sys,json\nfrom pathlib import Path\n'
                   'sys.stdin.read()\n'
                   'p=Path(sys.argv[sys.argv.index("--output-last-message")+1]);assert not p.exists()\n'
                   f'p.write_text({final!r})\n'
                   f'events=json.loads({json.dumps(pre + end)!r})\n'
                   'for event in events: print(json.dumps(event))\n'
                   + ('print("{",end="")\n' if case == 'truncated' else '')
                   + f'sys.exit({exit_code})\n')
    exe.chmod(0o700)
    return exe


def test_known_warning_requires_complete_final_and_is_persisted(tmp_path):
    exe = offline_cli(tmp_path)
    evidence_root = tmp_path / 'private'
    output, evidence = codex_document(str(exe), MODEL, 'offline input', tmp_path,
        threading.Event(), lambda _: None, diagnostics_root=evidence_root)
    assert output == 'offline result'
    assert evidence['warning_codes'] == ['CLI_MODEL_METADATA_FALLBACK']
    assert evidence['diagnostic_codes'] == []
    assert evidence['exit_code'] == 0 and evidence['final_result_extraction'] == 'PASSED'
    assert evidence['returned_model'] == 'NOT_REPORTED_BY_CLI'
    assert evidence['cli_invocations'] == 1 and not evidence['application_automatic_retry']
    receipt = evidence_root / evidence['private_evidence']['receipt_id']
    saved = json.loads((receipt / 'receipt.json').read_text())
    assert saved['state'] == 'CAPTURED' and saved['failure_point'] is None
    assert saved['events'][1]['warning_code'] == 'CLI_MODEL_METADATA_FALLBACK'
    assert json.loads((receipt / 'diagnostics.json').read_text())[0]['event'] == WARNING
    assert not (Path(tempfile.gettempdir()) / saved['binding']['result_directory_nonce']).exists()
    assert evidence['temporary_result_cleanup'] == 'REMOVED'


@pytest.mark.parametrize('case,code', [
    ('wrong_model', 'PROVIDER_REQUEST_FAILED'), ('after_start', 'PROVIDER_REQUEST_FAILED'),
    ('terminal_error', 'PROVIDER_REQUEST_FAILED'), ('failed_turn', 'PROVIDER_REQUEST_FAILED'),
    ('nonzero', 'EXECUTION_INCOMPLETE'), ('mismatch', 'RESULT_FINAL_AMBIGUOUS'),
    ('no_terminal', 'EXECUTION_INCOMPLETE'), ('conflicting_terminal', 'RESULT_TERMINAL_CONFLICT'),
    ('refusal', 'PROVIDER_REFUSED'), ('duplicate_item', 'RESULT_ITEM_CONFLICT'),
    ('truncated', 'RESULT_EVENT_STREAM_INCOMPLETE'),
])
def test_warning_never_bypasses_other_failures(tmp_path, case, code):
    exe = offline_cli(tmp_path, case)
    with pytest.raises(ExecutionFailure) as exc:
        codex_document(str(exe), MODEL, 'offline', tmp_path, threading.Event(), lambda _: None,
                       diagnostics_root=tmp_path / 'private')
    assert exc.value.code == code
    assert exc.value.evidence['cli_invocations'] == 1
    assert exc.value.evidence['private_evidence']['persistence'] == 'SAVED'
    assert exc.value.evidence['temporary_result_cleanup'] == 'REMOVED'


@pytest.mark.parametrize('mutation', ['missing_thread', 'wrong_text', 'extra_field', 'bad_id', 'top_error', 'duplicate', 'none', 'array'])
def test_only_exact_bound_preturn_advisory_is_allowlisted(mutation):
    stream = EventStream()
    if mutation != 'missing_thread': stream.accept({'type': 'thread.started', 'thread_id': 'offline'})
    event = copy.deepcopy(WARNING)
    if mutation == 'wrong_text': event['item']['message'] += ' Fatal failure.'
    if mutation == 'extra_field': event['fatal'] = True
    if mutation == 'bad_id': event['item']['id'] = '../outside'
    if mutation == 'top_error': event = {'type': 'error', 'message': WARNING['item']['message']}
    if mutation == 'duplicate': assert stream.accept_metadata_warning(event, MODEL)
    if mutation == 'none': event = None
    if mutation == 'array': event = []
    assert stream.accept_metadata_warning(event, MODEL) is False
