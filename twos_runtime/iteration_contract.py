"""One shipped schema for CLI producer and strict local consumer.

The supported subset is intentionally small; unsupported schema constructs fail
closed. Semantic, baseline and permission checks remain in the controller.
"""
import hashlib
import json
from pathlib import Path
import sys


def schema_path(role):
    name = {'executor': 'iteration-patch', 'reviewer': 'iteration-review'}[role]
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    return root / 'static_cockpit' / 'project_first' / (name + '.schema.json')


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key')
        value[key] = item
    return value


def validate(value, schema):
    if set(schema) - {'type', 'additionalProperties', 'required', 'properties', 'enum'}:
        raise ValueError('unsupported contract keyword')
    if schema['type'] == 'object':
        if type(value) is not dict or schema.get('additionalProperties') is not False:
            raise ValueError('object contract')
        if set(value) != set(schema['required']) or set(value) != set(schema['properties']):
            raise ValueError('exact fields required')
        for name, child in schema['properties'].items():
            validate(value[name], child)
    elif schema['type'] == 'string':
        if type(value) is not str:
            raise ValueError('string contract')
    else:
        raise ValueError('unsupported contract type')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('contract enum')


def parse(output, role):
    value = json.loads(output, object_pairs_hook=unique_object)
    validate(value, json.loads(schema_path(role).read_bytes()))
    return value


def identity():
    names=('iteration_contract.py','execution_evidence.py','project_execution.py','iteration_studio.py','iteration_candidate.py')
    if getattr(sys,'frozen',False):
        provenance=Path(sys.executable).resolve().parents[1]/'source-provenance.json'
        hashes=json.loads(provenance.read_bytes())['input_hashes']
        controller={name:hashes['twos_runtime/'+name] for name in names}
    else:
        controller={name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in names}
    return {'protocol': 'TWOS_STRUCTURED_RESULT_2',
            'schemas': {role: hashlib.sha256(schema_path(role).read_bytes()).hexdigest()
                        for role in ('executor', 'reviewer')},
            'adapter': 'CODEX_EXEC_FINAL_FILE_3',
            'controller_input_hashes':controller,
            'verification': 'IMMUTABLE_BASELINE_BOTH_LOCALES_2'}
