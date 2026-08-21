from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select, text

import twos_runtime.codex_connectivity as connectivity_module
from tests.test_self_hosting import make_source_repo
from twos_runtime.app import create_app
from twos_runtime.codex_adapter import CodexModelCatalog, CodexModelCatalogEntry
from twos_runtime.config import STATIC_COCKPIT_DIR, TWOS_UI_PATH, Settings
from twos_runtime.models import (
    CodexConnectivityEvidence,
    CodexRun,
    CodexResultEnvelope,
    DeliveryCandidate,
    SchemaVersion,
)
from twos_runtime.result_intake import result_envelope_out, sanitize_result_value


MODEL = "fixture-connectivity-model"
SECOND_MODEL = "fixture-connectivity-model-2"
PASSWORD = "connectivity-owner-password"


class _FakeDirectExecControlRunner:
    """Return bounded control outcomes without starting Codex or a subprocess."""

    def __init__(self, *, normal: bool, detached: bool) -> None:
        self._results = {"normal": normal, "detached": detached}
        self.invocations: list[str] = []

    def run(self, context: str) -> bool:
        self.invocations.append(context)
        return self._results[context]


def _fake_codex(tmp_path: Path, mode: str = "success") -> Path:
    executable = tmp_path / "connectivity-codex"
    mode_path = executable.with_suffix(".mode")
    mode_path.write_text(mode)
    executable.write_text(
        """#!/usr/bin/env python3
import json
import os
import pathlib
import sys
import time

root = pathlib.Path(__file__).parent
# executable-identity-marker-A
mode = pathlib.Path(__file__).with_suffix('.mode').read_text().strip()
args = sys.argv[1:]
if args == ['--version']:
    version_path = pathlib.Path(__file__).with_suffix('.version')
    print(version_path.read_text().strip() if version_path.exists() else 'codex-cli 0.144.4')
    raise SystemExit(0)
if args == ['exec', '--help']:
    suffix = '' if mode == 'sidecar_unsupported' else ' --output-schema FILE --output-last-message FILE'
    print('Usage: codex exec --model MODEL --json --sandbox read-only' + suffix)
    raise SystemExit(0)
if args == ['login', '--help']:
    print('Usage: codex login [status]')
    raise SystemExit(0)
if args == ['login', 'status']:
    if mode == 'auth_required':
        print('Not logged in', file=sys.stderr)
        raise SystemExit(1)
    if mode == 'credential_store':
        print('Credential store unavailable: permission denied', file=sys.stderr)
        raise SystemExit(1)
    if mode == 'api_key':
        print('Logged in with API key')
        raise SystemExit(0)
    print('Logged in with ChatGPT')
    raise SystemExit(0)

if args == ['app-server', '-c', 'mcp_servers={}', '--strict-config', '--listen', 'stdio://']:
    root.joinpath('app-server-count').write_text(
        str(int(root.joinpath('app-server-count').read_text()) + 1)
        if root.joinpath('app-server-count').exists() else '1'
    )
    root.joinpath('probe-count').write_text(
        str(int(root.joinpath('probe-count').read_text()) + 1)
        if root.joinpath('probe-count').exists() else '1'
    )
    root.joinpath('environment-shape.json').write_text(json.dumps({
        'api_key_present': 'OPENAI_API_KEY' in os.environ,
        'proxy_present': 'HTTPS_PROXY' in os.environ,
    }, sort_keys=True))
    if mode == 'mutates_workspace':
        pathlib.Path('unexpected.txt').write_text('forbidden')
    thread_id = 'connectivity-thread'
    turn_id = 'connectivity-turn'
    thread_model = ''
    for line in sys.stdin:
        message = json.loads(line)
        method = message.get('method')
        if method == 'initialize':
            capabilities = message.get('params', {}).get('capabilities', {})
            assert capabilities == {
                'experimentalApi': False,
                'mcpServerOpenaiFormElicitation': False,
                'optOutNotificationMethods': [],
                'requestAttestation': False,
            }
            if mode == 'partial_frame':
                sys.stdout.write('{"id":')
                sys.stdout.flush()
                time.sleep(4)
                raise SystemExit(1)
            if mode == 'malformed_jsonl':
                print('malformed connectivity output', flush=True)
            print(json.dumps({
                'id': message['id'],
                'result': {
                    'userAgent': 'fixture',
                    'platformFamily': 'unix',
                    'platformOs': 'test',
                    'codexHome': os.environ.get('CODEX_HOME'),
                },
            }), flush=True)
            if mode in {
                'success', 'remote_control_disabled', 'remote_control_active',
                'unknown_noncritical', 'unknown_critical', 'account_updated'
            }:
                print(json.dumps({
                    'method': 'remoteControl/status/changed',
                    'params': {
                        'environmentId': None,
                        'installationId': 'fixture-installation-id-secret',
                        'serverName': 'fixture-server-name-secret',
                        'status': 'connected' if mode == 'remote_control_active' else 'disabled',
                    },
                }), flush=True)
            if mode == 'unknown_noncritical':
                print(json.dumps({
                    'method': 'telemetry/presentationHint',
                    'params': {
                        'secret': 'fixture-unknown-secret-token',
                        'progress': 1,
                    },
                }), flush=True)
            if mode == 'unknown_critical':
                print(json.dumps({
                    'method': 'model/futureVerification',
                    'params': {
                        'secret': 'fixture-critical-secret-token',
                        'network': 'unreachable',
                    },
                }), flush=True)
            if mode == 'account_updated':
                print(json.dumps({
                    'method': 'account/updated',
                    'params': {'authMode': 'chatgpt', 'planType': 'plus'},
                }), flush=True)
        elif method == 'mcpServerStatus/list':
            data = (
                [{
                    'name': 'forbidden-mcp',
                    'authStatus': 'unsupported',
                    'resourceTemplates': [],
                    'resources': [],
                    'tools': {},
                }]
                if mode == 'mcp_inventory'
                else []
            )
            print(json.dumps({
                'id': message['id'],
                'result': {'data': data, 'nextCursor': None},
            }), flush=True)
        elif method == 'thread/start':
            params = message.get('params', {})
            assert params.get('allowProviderModelFallback') is False
            assert params.get('sandbox') == 'read-only'
            assert params.get('ephemeral') is True
            assert params.get('modelProvider') == 'openai'
            assert params.get('config') == {
                'mcp_servers': {}, 'web_search': 'disabled'
            }
            assert params.get('dynamicTools') == []
            assert params.get('runtimeWorkspaceRoots') == [params.get('cwd')]
            assert params.get('selectedCapabilityRoots') == []
            thread_model = str(params.get('model') or '')
            if mode == 'model_unavailable':
                print('requested model is unavailable for this account', file=sys.stderr, flush=True)
                print(json.dumps({
                    'id': message['id'],
                    'error': {'code': -32000, 'message': 'requested model is unavailable'},
                }), flush=True)
                raise SystemExit(2)
            response_model = (
                '' if mode == 'actual_unobserved'
                else thread_model
            )
            if mode == 'premature_turn':
                premature_turn = {'id': turn_id, 'items': [], 'status': 'inProgress'}
                print(json.dumps({
                    'method': 'turn/started',
                    'params': {'threadId': thread_id, 'turn': premature_turn},
                }), flush=True)
            print(json.dumps({
                'id': message['id'],
                'result': {
                    'model': response_model,
                    'modelProvider': 'fixture-provider-mismatch'
                    if mode == 'provider_mismatch' else 'openai',
                    'cwd': params.get('cwd'),
                    'approvalPolicy': 'never',
                    'approvalsReviewer': 'user',
                    'sandbox': {
                        'type': 'workspaceWrite'
                        if mode == 'unsafe_thread_policy' else 'readOnly',
                        'networkAccess': False,
                    },
                    'instructionSources': (
                        ['/fixture/unsafe-instructions']
                        if mode == 'unsafe_thread_policy' else []
                    ),
                    'runtimeWorkspaceRoots': params.get('runtimeWorkspaceRoots'),
                    'thread': {'id': thread_id, 'ephemeral': True},
                },
            }), flush=True)
        elif method == 'turn/start':
            params = message.get('params', {})
            assert params.get('threadId') == thread_id
            assert params.get('model') == thread_model
            if mode == 'interactive_prompt':
                print('Open this URL; waiting for browser authentication', file=sys.stderr, flush=True)
                time.sleep(4)
                raise SystemExit(1)
            if mode == 'provider_unreachable':
                print('network unreachable: failed to connect to provider', file=sys.stderr, flush=True)
                raise SystemExit(2)
            started_turn = {'id': turn_id, 'items': [], 'status': 'inProgress'}
            completed_item = {
                'id': 'message-1',
                'type': 'agentMessage',
                'text': 'TWOS_CODEX_CONNECTION_OK',
            }
            print(json.dumps({
                'id': message['id'], 'result': {'turn': started_turn}
            }), flush=True)
            started_thread = 'wrong-thread' if mode == 'lifecycle_conflict' else thread_id
            print(json.dumps({
                'method': 'turn/started',
                'params': {'threadId': started_thread, 'turn': started_turn},
            }), flush=True)
            if mode == 'model_verification':
                print(json.dumps({
                    'method': 'model/verification',
                    'params': {
                        'threadId': thread_id,
                        'turnId': turn_id,
                        'verifications': ['trustedAccessForCyber'],
                    },
                }), flush=True)
            if mode == 'guardian_warning':
                print(json.dumps({
                    'method': 'guardianWarning',
                    'params': {
                        'threadId': thread_id,
                        'message': 'fixture guardian warning secret detail',
                    },
                }), flush=True)
            if mode == 'terminal_error':
                print(json.dumps({
                    'method': 'error',
                    'params': {
                        'threadId': thread_id,
                        'turnId': turn_id,
                        'willRetry': False,
                        'error': {
                            'message': 'fixture terminal error',
                            'codexErrorInfo': 'other',
                        },
                    },
                }), flush=True)
            if mode in {'current_time_request', 'unknown_request', 'approval_request'}:
                request_method = (
                    'currentTime/read'
                    if mode == 'current_time_request'
                    else 'future/request'
                    if mode == 'unknown_request'
                    else 'item/commandExecution/requestApproval'
                )
                print(json.dumps({
                    'id': 'server-request-1',
                    'method': request_method,
                    'params': {
                        'threadId': thread_id,
                        'turnId': turn_id,
                        'itemId': 'fixture-item',
                    },
                }), flush=True)
                response = json.loads(sys.stdin.readline())
                root.joinpath('server-response.json').write_text(json.dumps(response, sort_keys=True))
            if mode == 'tool_attempt':
                print(json.dumps({
                    'method': 'item/started',
                    'params': {
                        'threadId': thread_id,
                        'turnId': turn_id,
                        'startedAtMs': 1,
                        'item': {
                            'id': 'forbidden-tool',
                            'type': 'commandExecution',
                            'command': 'touch forbidden',
                        },
                    },
                }), flush=True)
            if mode == 'conflicting_actual':
                for target in ('conflicting-connectivity-model-a', 'conflicting-connectivity-model-b'):
                    print(json.dumps({
                        'method': 'model/rerouted',
                        'params': {
                            'fromModel': thread_model,
                            'toModel': target,
                            'reason': 'highRiskCyberActivity',
                            'threadId': thread_id,
                            'turnId': turn_id,
                        },
                    }), flush=True)
            elif mode == 'unsupported_actual':
                print(json.dumps({
                    'method': 'model/rerouted',
                    'params': {
                        'fromModel': thread_model,
                        'toModel': 'unsupported-connectivity-model',
                        'reason': 'highRiskCyberActivity',
                        'threadId': thread_id,
                        'turnId': turn_id,
                    },
                }), flush=True)
            elif mode == 'supported_reroute':
                print(json.dumps({
                    'method': 'model/rerouted',
                    'params': {
                        'fromModel': thread_model,
                        'toModel': 'fixture-connectivity-model-2',
                        'reason': 'highRiskCyberActivity',
                        'threadId': thread_id,
                        'turnId': turn_id,
                    },
                }), flush=True)
            if mode == 'secret_output':
                print(
                    'Authorization: Bearer fixture-secret-token-123456 '
                    'OPENAI_API_KEY=sk-fixturesecret123456 /usr/local/private-fixture',
                    file=sys.stderr,
                    flush=True,
                )
            print(json.dumps({
                'method': 'item/completed',
                'params': {
                    'threadId': thread_id,
                    'turnId': turn_id,
                    'completedAtMs': 1,
                    'item': completed_item,
                },
            }), flush=True)
            print(json.dumps({
                'method': 'turn/completed',
                'params': {
                    'threadId': thread_id,
                    'turn': {
                        'id': turn_id,
                        'items': [
                            {**completed_item, 'text': 'different terminal response'}
                            if mode == 'terminal_mismatch' else completed_item
                        ],
                        'status': 'failed' if mode == 'turn_failure' else 'completed',
                        'error': {'message': 'fixture turn failed', 'codexErrorInfo': 'other'}
                        if mode == 'turn_failure' else None,
                    },
                },
            }), flush=True)
        elif method == 'thread/unsubscribe':
            print(json.dumps({
                'id': message['id'], 'result': {'status': 'unsubscribed'}
            }), flush=True)
    raise SystemExit(0)

root.joinpath('probe-count').write_text(
    str(int(root.joinpath('probe-count').read_text()) + 1)
    if root.joinpath('probe-count').exists() else '1'
)
root.joinpath('exec-count').write_text(
    str(int(root.joinpath('exec-count').read_text()) + 1)
    if root.joinpath('exec-count').exists() else '1'
)
root.joinpath('environment-shape.json').write_text(json.dumps({
    'api_key_present': 'OPENAI_API_KEY' in os.environ,
    'proxy_present': 'HTTPS_PROXY' in os.environ,
}, sort_keys=True))
prompt = sys.stdin.read()
model = args[2] if len(args) > 2 else ''
def option(name):
    return args[args.index(name) + 1] if name in args else ''
schema_path = option('--output-schema')
last_message_path = option('--output-last-message')
root.joinpath('exec-shape.json').write_text(json.dumps({
    'json': '--json' in args,
    'ephemeral': '--ephemeral' in args,
    'ignore_user_config': '--ignore-user-config' in args,
    'sandbox': option('--sandbox'),
    'model': option('--model'),
    'schema_sidecar': bool(schema_path),
    'last_message_sidecar': bool(last_message_path),
    'stdin_sentinel': bool(args and args[-1] == '-'),
}, sort_keys=True))
if schema_path:
    schema = json.loads(pathlib.Path(schema_path).read_text())
    assert schema['required'] == ['status']
    assert schema['properties']['status']['const'] == 'TWOS_CODEX_CONNECTION_OK'
if mode == 'malformed_jsonl':
    print('malformed connectivity output', flush=True)
if mode == 'provider_unreachable':
    print('network unreachable: failed to connect to provider', file=sys.stderr)
    raise SystemExit(2)
if mode == 'model_unavailable':
    print('requested model is unavailable for this account', file=sys.stderr)
    raise SystemExit(2)
if mode == 'interactive_prompt':
    print('Open this URL; waiting for browser authentication', file=sys.stderr, flush=True)
    time.sleep(4)
    raise SystemExit(1)
if mode == 'mutates_workspace':
    pathlib.Path('unexpected.txt').write_text('forbidden')

def emit(value):
    print(json.dumps(value, separators=(',', ':')), flush=True)

response = {'status': 'TWOS_CODEX_CONNECTION_OK'}
response_text = json.dumps(response, separators=(',', ':'))
if last_message_path and mode != 'missing_sidecar':
    pathlib.Path(last_message_path).write_text(
        json.dumps({'status': 'WRONG'}) if mode == 'sidecar_mismatch' else response_text
    )

thread = {'type': 'thread.started', 'thread_id': 'connectivity-thread'}
if mode == 'requested_echo':
    thread['model'] = model
elif mode == 'unsupported_actual':
    thread['actual_model_identifier'] = 'unsupported-connectivity-model'
elif mode == 'supported_reroute':
    thread['actual_model_identifier'] = 'fixture-connectivity-model-2'
elif mode == 'conflicting_actual':
    thread['actual_model_identifier'] = model
else:
    if mode != 'actual_unobserved':
        thread['actual_model_identifier'] = model
emit(thread)
emit({'type': 'turn.started', 'turn_id': 'connectivity-turn'})
if mode == 'unexpected_action':
    emit({'type': 'item.completed', 'item': {
        'id': 'command-1', 'type': 'command_execution', 'command': 'pwd'
    }})
emit({'type': 'item.completed', 'item': {
    'id': 'message-1', 'type': 'agent_message', 'text': response_text
}})
if mode == 'failed_then_completed':
    emit({'type': 'turn.failed', 'turn_id': 'connectivity-turn'})
if mode == 'secret_output':
    print('Authorization: Bearer fixture-secret-token-123456 OPENAI_API_KEY=sk-fixturesecret123456 /usr/local/private-fixture', file=sys.stderr)
terminal = {
    'type': 'turn.completed',
    'turn_id': 'different-connectivity-turn' if mode == 'lifecycle_conflict' else 'connectivity-turn',
}
if mode == 'requested_echo':
    terminal['model'] = model
elif mode == 'conflicting_actual':
    terminal['actual_model_identifier'] = 'conflicting-connectivity-model'
elif mode == 'supported_reroute':
    terminal['actual_model_identifier'] = 'fixture-connectivity-model-2'
elif mode != 'actual_unobserved':
    terminal['actual_model_identifier'] = (
        'unsupported-connectivity-model' if mode == 'unsupported_actual' else model
    )
if mode != 'incomplete_lifecycle':
    emit(terminal)
raise SystemExit(0)
"""
    )
    executable.chmod(0o755)
    return executable


def _client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str = "success",
    extra_models: tuple[str, ...] = (),
) -> tuple[TestClient, Path, Path]:
    source_repo = make_source_repo(tmp_path)
    executable = _fake_codex(tmp_path, mode)
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "auth.json").write_text("{}")
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'connectivity.sqlite3'}",
        scheduler_poll_seconds=0.05,
        static_cockpit_dir=STATIC_COCKPIT_DIR,
        ui_path=TWOS_UI_PATH,
        source_repo=source_repo,
        worktree_root=tmp_path / "worktrees",
        codex_executable=str(executable),
        codex_timeout_seconds=301,
        codex_connectivity_timeout_seconds=1,
    )
    app = create_app(settings=settings, start_scheduler=False)
    catalog = CodexModelCatalog(
        status="available",
        source="controlled_test_fixture",
        version="connectivity-test.v1",
        installed_cli_version="codex-cli 0.144.4",
        warnings=(),
        models=tuple(
            CodexModelCatalogEntry(
                adapter_id="codex_cli",
                provider_id="local_codex_cli",
                canonical_model_id=identifier,
                display_name=f"Connectivity fixture model {index + 1}",
                aliases=(),
                selectable=True,
                recommended=index == 0,
                lifecycle_status="current",
                compatibility_status="controlled_test_fixture",
                compatibility_source="controlled_test_fixture",
                catalog_version="connectivity-test.v1",
                supported_capabilities=("coding", "verification"),
                purpose="Non-networked connectivity fixture.",
            )
            for index, identifier in enumerate((MODEL, *extra_models))
        ),
    )
    app.state.codex_manager.adapter._model_catalog_cache = catalog
    app.state.codex_manager.adapter._model_catalog_cached_at = time.monotonic()
    client = TestClient(app)
    return client, executable, source_repo


def _signup(client: TestClient, username: str = "owner") -> None:
    response = client.post(
        "/api/auth/signup",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 201, response.text


def _verify(client: TestClient) -> dict:
    response = client.post(
        "/api/codex/setup/verify-connection",
        json={"model_identifier": MODEL, "capability": "coding"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _legacy_app_server_probe(tmp_path: Path, mode: str = "success") -> tuple[dict, Path]:
    executable = _fake_codex(tmp_path, mode=mode)
    probe = connectivity_module._app_server_connectivity_probe(
        str(executable),
        MODEL,
        environment=dict(os.environ),
        timeout_seconds=2,
    )
    return probe, executable


def test_vol18_005_migration_and_append_only_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _ = _client(tmp_path, monkeypatch)
    with client:
        factory = client.app.state.session_factory
        with factory() as session:
            versions = set(session.scalars(select(SchemaVersion.version)).all())
            assert "vol18.005" in versions
        inspector = inspect(client.app.state.engine)
        assert "codex_connectivity_evidence" in inspector.get_table_names()
        triggers = {
            row[0]
            for row in client.app.state.engine.connect().execute(
                text("SELECT name FROM sqlite_master WHERE type='trigger'")
            )
        }
        assert "trg_codex_connectivity_evidence_no_update" in triggers
        assert "trg_codex_connectivity_evidence_no_delete" in triggers


def test_get_is_authenticated_and_never_runs_provider_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, executable, _ = _client(tmp_path, monkeypatch)
    marker = executable.parent / "probe-count"
    with client:
        assert client.get("/api/codex/setup/connectivity").status_code == 401
        _signup(client)
        result = client.get("/api/codex/setup/connectivity")
        assert result.status_code == 200
        payload = result.json()
        assert payload["readiness_state"] == "AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED"
        assert payload["ready_for_real_run"] is False
        assert payload["authentication"]["state"] == "CHATGPT_LOGIN_AUTHENTICATED"
        assert payload["authentication"]["authenticated"] is True
        assert payload["authentication"]["method"] == "ChatGPT login"
        assert payload["authentication"]["credential_store"] == "file"
        assert payload["authentication"]["credential_store_accessible"] is True
        assert payload["authentication"]["native_login_command"] is None
        assert payload["configured_run_timeout_seconds"] == 301
        assert not marker.exists()
        with client.app.state.session_factory() as session:
            assert session.query(CodexConnectivityEvidence).count() == 0
            assert session.query(CodexRun).count() == 0
            assert session.query(DeliveryCandidate).count() == 0


def test_successful_owner_probe_captures_actual_model_and_is_append_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, executable, source_repo = _client(tmp_path, monkeypatch)
    before = subprocess.run(
        ["git", "status", "--porcelain=v1"], cwd=source_repo, capture_output=True, text=True, check=True
    ).stdout
    with client:
        _signup(client)
        payload = _verify(client)
        assert payload["readiness_state"] == "READY_FOR_REAL_RUN"
        assert payload["ready_for_real_run"] is True
        assert payload["provider_reachable"] is True
        assert payload["model_available"] is True
        assert payload["actual_model"] == MODEL
        assert payload["requested_model"] == MODEL
        assert payload["advanced"]["sanitized_command"].startswith(
            "codex exec --model <requested-model> --json --sandbox read-only"
        )
        diagnostics = payload["advanced"]["diagnostics"]
        assert diagnostics["transport"] == "codex_exec_jsonl"
        assert diagnostics["app_server_probe_performed"] is False
        assert diagnostics["structured_response"]["last_message_match"] is True
        assert not (executable.parent / "app-server-count").exists()
        assert json.loads((executable.parent / "exec-shape.json").read_text()) == {
            "ephemeral": True,
            "ignore_user_config": True,
            "json": True,
            "last_message_sidecar": True,
            "model": MODEL,
            "sandbox": "read-only",
            "schema_sidecar": True,
            "stdin_sentinel": True,
        }
        assert str(executable) not in json.dumps(payload)
        assert "/private/" not in json.dumps(payload)
        assert payload["configured_run_timeout_seconds"] == 301
        get_again = client.get(
            "/api/codex/setup/connectivity", params={"model_identifier": MODEL}
        ).json()
        assert get_again["evidence_id"] == payload["evidence_id"]
        assert (executable.parent / "probe-count").read_text() == "1"
        with client.app.state.session_factory() as session:
            row = session.scalar(select(CodexConnectivityEvidence))
            assert row is not None
            assert session.query(CodexRun).count() == 0
            assert session.query(DeliveryCandidate).count() == 0
            row.safe_summary = "forbidden mutation"
            with pytest.raises(Exception):
                session.commit()
            session.rollback()
            with pytest.raises(Exception):
                session.delete(row)
                session.commit()
    after = subprocess.run(
        ["git", "status", "--porcelain=v1"], cwd=source_repo, capture_output=True, text=True, check=True
    ).stdout
    assert before == after == ""


def test_prerequisite_recheck_preserves_matching_owner_probe_without_provider_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, executable, _ = _client(tmp_path, monkeypatch)
    probe_count = executable.parent / "probe-count"
    with client:
        _signup(client)
        verified = _verify(client)
        assert probe_count.read_text() == "1"

        checked = client.post(
            "/api/codex/setup/check",
            json={"model_identifier": MODEL, "capability": "coding"},
        )
        assert checked.status_code == 200, checked.text
        payload = checked.json()
        assert payload["available"] is True
        assert payload["ready_for_real_run"] is True
        assert payload["readiness_state"] == "READY_FOR_REAL_RUN"
        assert payload["provider_probe_performed"] is False
        assert payload["connectivity_evidence_id"] == verified["evidence_id"]
        assert payload["availability_evidence"]["result"] == "available"
        assert payload["availability_evidence"]["evidence_type"] == (
            "non_inference_cli_health_with_persisted_connectivity"
        )
        assert payload["configuration"]["availability_status"] == "available"
        assert payload["invalidated_packs"] == 0
        assert probe_count.read_text() == "1"
        with client.app.state.session_factory() as session:
            assert session.query(CodexConnectivityEvidence).count() == 1


def test_detection_loss_downgrades_and_restored_cli_requires_new_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, executable, _ = _client(tmp_path, monkeypatch)
    unavailable = executable.with_suffix(".temporarily-unavailable")
    with client:
        _signup(client)
        first = _verify(client)
        assert first["ready_for_real_run"] is True
        executable.rename(unavailable)
        try:
            observed = client.post(
                "/api/codex/setup/check",
                json={"model_identifier": MODEL, "capability": "coding"},
            )
            assert observed.status_code == 200, observed.text
            assert observed.json()["available"] is False
            assert observed.json()["ready_for_real_run"] is False
            assert observed.json()["availability_evidence"]["result"] == "unavailable"
            assert observed.json()["availability_evidence"]["failure_classification"] == (
                "runtime_unavailable"
            )
            assert observed.json()["configuration"]["availability_status"] == "unavailable"
        finally:
            unavailable.rename(executable)

        restored = client.get(
            "/api/codex/setup/connectivity", params={"model_identifier": MODEL}
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["readiness_state"] == (
            "AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED"
        )
        assert restored.json()["ready_for_real_run"] is False
        assert "invalidated" in restored.json()["blocker"].casefold()

        rechecked = client.post(
            "/api/codex/setup/check",
            json={"model_identifier": MODEL, "capability": "coding"},
        )
        assert rechecked.status_code == 200, rechecked.text
        assert rechecked.json()["available"] is False
        assert rechecked.json()["provider_probe_performed"] is False
        assert (executable.parent / "probe-count").read_text() == "1"

        second = _verify(client)
        assert second["ready_for_real_run"] is True
        assert second["evidence_id"] != first["evidence_id"]
        assert (executable.parent / "probe-count").read_text() == "2"


@pytest.mark.parametrize(
    ("mode", "state", "blocker"),
    [
        ("auth_required", "AUTHENTICATION_REQUIRED", "AUTHENTICATION_REQUIRED"),
        ("credential_store", "BLOCKED", "CREDENTIAL_STORE_UNAVAILABLE"),
        ("provider_unreachable", "PROVIDER_UNREACHABLE", "PROVIDER_UNREACHABLE"),
        ("model_unavailable", "MODEL_UNAVAILABLE", "MODEL_UNAVAILABLE"),
        ("interactive_prompt", "AUTHENTICATION_REQUIRED", "INTERACTIVE_PROMPT_DETECTED"),
        ("unsupported_actual", "MODEL_UNAVAILABLE", "ACTUAL_MODEL_UNSUPPORTED"),
        ("conflicting_actual", "BLOCKED", "ACTUAL_MODEL_CONFLICT"),
        ("lifecycle_conflict", "BLOCKED", "PROBE_LIFECYCLE_CONFLICT"),
        ("failed_then_completed", "BLOCKED", "PROBE_LIFECYCLE_CONFLICT"),
        ("malformed_jsonl", "BLOCKED", "PROBE_MALFORMED_JSONL"),
        ("mutates_workspace", "BLOCKED", "PROBE_MUTATED_WORKSPACE"),
        ("unexpected_action", "BLOCKED", "PROBE_UNEXPECTED_ACTION"),
        ("sidecar_unsupported", "BLOCKED", "EXEC_SIDECAR_UNSUPPORTED"),
        ("missing_sidecar", "BLOCKED", "PROBE_SIDECAR_MISMATCH"),
        ("sidecar_mismatch", "BLOCKED", "PROBE_SIDECAR_MISMATCH"),
        ("incomplete_lifecycle", "BLOCKED", "PROBE_EVIDENCE_INCOMPLETE"),
    ],
)
def test_truthful_probe_blockers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    state: str,
    blocker: str,
) -> None:
    client, _, _ = _client(tmp_path, monkeypatch, mode=mode)
    with client:
        _signup(client)
        payload = _verify(client)
        assert payload["readiness_state"] == state
        assert payload["blocker_code"] == blocker
        assert payload["ready_for_real_run"] is False
        assert payload["actual_model"] is None or payload["model_available"] is False
        if blocker == "ACTUAL_MODEL_UNOBSERVED":
            assert payload["provider_reachable"] is True


def test_completed_exec_turn_records_explicit_actual_model_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = _client(tmp_path, monkeypatch)
    with client:
        _signup(client)
        payload = _verify(client)
        assert payload["readiness_state"] == "READY_FOR_REAL_RUN"
        assert payload["actual_model"] == MODEL
        assert payload["advanced"]["diagnostics"]["structured_lifecycle"][
            "actual_model_source"
        ] == "actual_model_identifier"
        assert payload["advanced"]["diagnostics"]["structured_lifecycle"][
            "same_thread_model_resolution"
        ] is True


def test_completed_exec_turn_without_actual_model_metadata_is_truthfully_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = _client(tmp_path, monkeypatch, mode="actual_unobserved")
    with client:
        _signup(client)
        payload = _verify(client)
        assert payload["readiness_state"] == "READY_FOR_REAL_RUN"
        assert payload["blocker_code"] is None
        assert payload["actual_model"] is None
        assert payload["ready_for_real_run"] is True
        assert payload["requested_model"] == MODEL
        assert payload["advanced"]["diagnostics"][
            "requested_model_argument_verified"
        ] is True


def test_app_server_probe_is_explicit_bounded_same_thread_and_read_only(
    tmp_path: Path,
) -> None:
    probe, _ = _legacy_app_server_probe(tmp_path)
    assert probe["exit_code"] == 0
    assert probe["source_mutated"] is False
    assert probe["protocol_failure_code"] == ""
    assert probe["parsed"]["thread_started"] is True
    assert probe["parsed"]["turn_started"] is True
    assert probe["parsed"]["turn_completed"] is True
    assert probe["parsed"]["actual_model"] == MODEL
    assert probe["parsed"]["response_ok"] is True


def test_exact_0144_remote_control_startup_notification_is_handled_without_readiness_claim(
    tmp_path: Path,
) -> None:
    probe, _ = _legacy_app_server_probe(tmp_path, mode="remote_control_disabled")
    assert probe["protocol_failure_code"] == ""
    diagnostics = probe["parsed"]
    transcript = diagnostics["protocol_transcript"]
    remote = next(
        entry
        for entry in transcript
        if entry.get("method") == "remoteControl/status/changed"
    )
    assert remote["classification"] == "SERVER_NOTIFICATION"
    assert remote["sequence"] == 2
    assert remote["known_method"] is True
    assert remote["criticality"] == "NON_CRITICAL"
    assert remote["disposition"] == "handled"
    assert "REMOTE_CONTROL_DISABLED" in diagnostics["protocol_warnings"]
    serialized = json.dumps(diagnostics)
    assert "fixture-installation-id-secret" not in serialized
    assert "fixture-server-name-secret" not in serialized
    assert diagnostics["protocol_schema"] == {
        "cli_version": "codex-cli 0.144.4",
        "schema_digest": "000f4e8b3331fce471cfa5d81c7676b7033c780dbf1198f0958933eb09f6d84a",
        "notification_registry_digest": "67669e13a8af9449da30acdbd83a6108fd54ed92b79849dee381aece1521937f",
        "request_registry_digest": "7c8a2c6fe03d6afdf8a83f91fa5eb55e7ae630fe2e43a167691ab917dccc9556",
        "version_match": True,
    }


def test_remote_control_connected_blocks_isolated_probe(
    tmp_path: Path,
) -> None:
    probe, _ = _legacy_app_server_probe(tmp_path, mode="remote_control_active")
    assert probe["protocol_failure_code"] == "APP_SERVER_REMOTE_CONTROL_ACTIVE"
    assert probe["parsed"]["provider_reachable"] is False


def test_unknown_noncritical_notification_is_redacted_warned_and_does_not_end_probe(
    tmp_path: Path,
) -> None:
    probe, _ = _legacy_app_server_probe(tmp_path, mode="unknown_noncritical")
    assert probe["protocol_failure_code"] == ""
    diagnostics = probe["parsed"]
    unknown = next(
        entry
        for entry in diagnostics["protocol_transcript"]
        if entry.get("method") == "telemetry/presentationHint"
    )
    assert unknown["known_method"] is False
    assert unknown["criticality"] == "NON_CRITICAL"
    assert unknown["disposition"] == "retained_warning"
    assert "UNKNOWN_NONCRITICAL_NOTIFICATION" in diagnostics["protocol_warnings"]
    assert "fixture-unknown-secret-token" not in json.dumps(diagnostics)


def test_unknown_critical_notification_is_protocol_blocker_not_provider_failure(
    tmp_path: Path,
) -> None:
    probe, _ = _legacy_app_server_probe(tmp_path, mode="unknown_critical")
    assert probe["protocol_failure_code"] == "PROTOCOL_COMPATIBILITY_BLOCKED"
    diagnostics = probe["parsed"]
    assert diagnostics["provider_reachable"] is False
    assert diagnostics["critical_protocol_method"] == "model/futureVerification"
    assert "fixture-critical-secret-token" not in json.dumps(diagnostics)
    assert "Provider unreachable" not in probe["protocol_failure_summary"]


def test_schema_version_mismatch_blocks_before_app_server_launch(tmp_path: Path) -> None:
    executable = _fake_codex(tmp_path)
    executable.with_suffix(".version").write_text("codex-cli 0.145.0")
    probe = connectivity_module._app_server_connectivity_probe(
        str(executable),
        MODEL,
        environment=dict(os.environ),
        timeout_seconds=2,
    )
    assert probe["protocol_failure_code"] == "PROTOCOL_SCHEMA_VERSION_MISMATCH"
    assert probe["parsed"]["protocol_schema"]["version_match"] is False
    assert not executable.parent.joinpath("probe-count").exists()


def test_model_verification_is_typed_safety_metadata_not_actual_model_source(
    tmp_path: Path,
) -> None:
    probe, _ = _legacy_app_server_probe(tmp_path, mode="model_verification")
    assert probe["protocol_failure_code"] == ""
    assert probe["parsed"]["actual_model_source"] == (
        "app_server_effective_turn_model"
    )
    assert "MODEL_TRUST_VERIFICATION_OBSERVED" in probe["parsed"][
        "protocol_warnings"
    ]


@pytest.mark.parametrize(
    ("mode", "blocker"),
    [
        ("guardian_warning", "APP_SERVER_GUARDIAN_WARNING"),
        ("terminal_error", "APP_SERVER_TURN_ERROR"),
        ("turn_failure", "APP_SERVER_TURN_FAILED"),
    ],
)
def test_known_critical_terminal_and_safety_notifications_block_truthfully(
    tmp_path: Path,
    mode: str,
    blocker: str,
) -> None:
    probe, _ = _legacy_app_server_probe(tmp_path, mode=mode)
    assert probe["protocol_failure_code"] == blocker
    assert "fixture guardian warning secret detail" not in json.dumps(
        probe["parsed"]
    )


def test_known_account_notification_is_typed_and_does_not_prove_readiness(
    tmp_path: Path,
) -> None:
    probe, _ = _legacy_app_server_probe(tmp_path, mode="account_updated")
    assert probe["protocol_failure_code"] == ""
    account_event = next(
        entry
        for entry in probe["parsed"]["protocol_transcript"]
        if entry.get("method") == "account/updated"
    )
    assert account_event["criticality"] == "CRITICAL"
    assert account_event["disposition"] == "handled"


def test_safe_supported_server_request_receives_exact_response(
    tmp_path: Path,
) -> None:
    probe, executable = _legacy_app_server_probe(
        tmp_path, mode="current_time_request"
    )
    assert probe["protocol_failure_code"] == ""
    response = json.loads(executable.parent.joinpath("server-response.json").read_text())
    assert response["id"] == "server-request-1"
    assert set(response) == {"id", "result"}
    assert set(response["result"]) == {"currentTimeAt"}
    assert type(response["result"]["currentTimeAt"]) is int


@pytest.mark.parametrize(
    ("mode", "blocker"),
    [
        ("unknown_request", "PROTOCOL_COMPATIBILITY_BLOCKED"),
        ("approval_request", "APP_SERVER_APPROVAL_REQUEST_BLOCKED"),
    ],
)
def test_unsupported_server_request_receives_error_and_never_auto_approves(
    tmp_path: Path,
    mode: str,
    blocker: str,
) -> None:
    probe, executable = _legacy_app_server_probe(tmp_path, mode=mode)
    response = json.loads(executable.parent.joinpath("server-response.json").read_text())
    assert response["id"] == "server-request-1"
    assert response["error"] == {
        "code": -32601,
        "message": "Method is not supported by the read-only TWOS connection probe.",
    }
    assert probe["protocol_failure_code"] == blocker


def test_app_server_partial_frame_is_bounded_without_blocking_readline(tmp_path: Path) -> None:
    executable = _fake_codex(tmp_path, mode="partial_frame")
    started = time.monotonic()
    probe = connectivity_module._app_server_connectivity_probe(
        str(executable),
        MODEL,
        environment=dict(os.environ),
        timeout_seconds=1,
    )
    assert time.monotonic() - started < 3
    assert probe["timed_out"] is True
    assert probe["partial_frame"] is True
    assert probe["protocol_failure_code"] == "APP_SERVER_PARTIAL_FRAME"


def test_same_turn_supported_reroute_requires_explicit_model_reselection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, _ = _client(
        tmp_path,
        monkeypatch,
        mode="supported_reroute",
        extra_models=(SECOND_MODEL,),
    )
    with client:
        _signup(client)
        catalogued = client.post(
            "/api/codex/setup/check",
            json={"model_identifier": SECOND_MODEL, "capability": "coding"},
        )
        assert catalogued.status_code == 200
        payload = _verify(client)
        assert payload["readiness_state"] == "MODEL_UNAVAILABLE"
        assert payload["blocker_code"] == "REQUESTED_MODEL_REROUTED"
        assert payload["ready_for_real_run"] is False
        assert payload["actual_model"] == SECOND_MODEL
        lifecycle = payload["advanced"]["diagnostics"]["structured_lifecycle"]
        assert lifecycle["actual_model_source"] == "actual_model_identifier"


def test_terminal_message_must_match_same_turn_completed_items(
    tmp_path: Path,
) -> None:
    probe, _ = _legacy_app_server_probe(tmp_path, mode="terminal_mismatch")
    assert probe["protocol_failure_code"] == "APP_SERVER_FINAL_MESSAGE_MISMATCH"


def test_generic_requested_model_echo_is_not_resolved_model_metadata() -> None:
    stdout = "\n".join(
        json.dumps(item)
        for item in (
            {"type": "thread.started", "thread_id": "echo-thread", "model": MODEL},
            {"type": "turn.started", "model_identifier": MODEL},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "TWOS_CODEX_CONNECTION_OK"},
            },
            {"type": "turn.completed", "model": MODEL},
        )
    ).encode()
    parsed = connectivity_module._parse_probe_jsonl(stdout, MODEL)
    assert parsed["actual_model"] == ""
    assert parsed["actual_model_source"] == ""


def test_probe_jsonl_rejects_out_of_order_and_partial_turn_identity() -> None:
    out_of_order = "\n".join(
        json.dumps(item)
        for item in (
            {"type": "turn.completed", "turn_id": "turn-1"},
            {"type": "turn.started", "turn_id": "turn-1"},
            {"type": "thread.started", "thread_id": "thread-1"},
        )
    ).encode()
    assert connectivity_module._parse_probe_jsonl(out_of_order, MODEL)[
        "lifecycle_conflict"
    ] is True

    partial_identity = "\n".join(
        json.dumps(item)
        for item in (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started", "turn_id": "turn-1"},
            {"type": "turn.completed"},
        )
    ).encode()
    assert connectivity_module._parse_probe_jsonl(partial_identity, MODEL)[
        "lifecycle_conflict"
    ] is True


def test_probe_jsonl_latches_turn_failure_before_later_completion() -> None:
    stdout = "\n".join(
        json.dumps(item)
        for item in (
            {"type": "thread.started", "thread_id": "thread-1"},
            {"type": "turn.started", "turn_id": "turn-1"},
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps(
                        {"status": connectivity_module.CONNECTIVITY_RESPONSE_MARKER}
                    ),
                },
            },
            {"type": "turn.failed", "turn_id": "turn-1"},
            {"type": "turn.completed", "turn_id": "turn-1"},
        )
    ).encode()

    parsed = connectivity_module._parse_probe_jsonl(stdout, MODEL)

    assert parsed["turn_failed"] is True
    assert parsed["turn_completed"] is False
    assert parsed["terminal_success"] is False
    assert parsed["lifecycle_conflict"] is True
    assert parsed["provider_reachable"] is False


def test_failed_owner_probe_blocker_and_timestamp_survive_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, executable, _ = _client(tmp_path, monkeypatch, mode="provider_unreachable")
    with client:
        _signup(client)
        failed = _verify(client)
        assert failed["readiness_state"] == "PROVIDER_UNREACHABLE"
        assert failed["last_connectivity_check"]

        refreshed = client.get(
            "/api/codex/setup/connectivity", params={"model_identifier": MODEL}
        )
        assert refreshed.status_code == 200, refreshed.text
        payload = refreshed.json()
        assert payload["evidence_id"] == failed["evidence_id"]
        assert payload["readiness_state"] == "PROVIDER_UNREACHABLE"
        assert payload["blocker_code"] == "PROVIDER_UNREACHABLE"
        assert payload["blocker"] == failed["blocker"]
        assert payload["last_connectivity_check"] == failed["last_connectivity_check"]
        assert payload["ready_for_real_run"] is False
        assert (executable.parent / "probe-count").read_text() == "1"


def test_provider_failure_and_sibling_recovery_cannot_resurrect_old_ready_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, executable, _ = _client(
        tmp_path, monkeypatch, extra_models=(SECOND_MODEL,)
    )
    mode_path = executable.with_suffix(".mode")
    with client:
        _signup(client)
        first = _verify(client)
        assert first["ready_for_real_run"] is True

        mode_path.write_text("provider_unreachable")
        failed = client.post(
            "/api/codex/setup/verify-connection",
            json={"model_identifier": SECOND_MODEL, "capability": "coding"},
        )
        assert failed.status_code == 200, failed.text
        assert failed.json()["readiness_state"] == "PROVIDER_UNREACHABLE"

        mode_path.write_text("success")
        recovered = client.post(
            "/api/codex/setup/verify-connection",
            json={"model_identifier": SECOND_MODEL, "capability": "coding"},
        )
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["readiness_state"] == "READY_FOR_REAL_RUN"

        stale_first = client.get(
            "/api/codex/setup/connectivity", params={"model_identifier": MODEL}
        )
        assert stale_first.status_code == 200, stale_first.text
        assert stale_first.json()["readiness_state"] == (
            "AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED"
        )
        assert stale_first.json()["ready_for_real_run"] is False
        assert "invalidated" in stale_first.json()["blocker"].casefold()


def test_api_key_and_proxy_context_reach_child_without_secret_exposure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-super-secret-connectivity-value-123456"
    proxy = "http://owner:proxy-secret@127.0.0.1:9"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    monkeypatch.setenv("HTTPS_PROXY", proxy)
    client, executable, _ = _client(tmp_path, monkeypatch, mode="api_key")
    with client:
        _signup(client)
        payload = _verify(client)
        rendered = json.dumps(payload)
        assert payload["authentication"]["state"] == "API_KEY_AUTHENTICATED"
        assert payload["authentication"]["credential_store"] == "environment"
        assert payload["authentication"]["credential_store_accessible"] is True
        assert payload["readiness_state"] == "READY_FOR_REAL_RUN"
        shape = json.loads((executable.parent / "environment-shape.json").read_text())
        assert shape == {"api_key_present": True, "proxy_present": True}
        assert secret not in rendered
        assert proxy not in rendered
        with client.app.state.session_factory() as session:
            evidence = session.scalar(select(CodexConnectivityEvidence))
            assert evidence is not None
            assert secret not in evidence.diagnostic_json
            assert proxy not in evidence.diagnostic_json


def test_detached_context_without_environment_key_is_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-detached-only-secret-123456")
    client, executable, _ = _client(tmp_path, monkeypatch, mode="api_key")
    original = connectivity_module.codex_child_environment

    def without_key() -> dict[str, str]:
        environment = original()
        environment.pop("OPENAI_API_KEY", None)
        return environment

    monkeypatch.setattr(connectivity_module, "codex_child_environment", without_key)
    with client:
        _signup(client)
        payload = _verify(client)
        assert payload["readiness_state"] == "BLOCKED"
        assert payload["blocker_code"] == "DETACHED_CREDENTIALS_UNAVAILABLE"
        assert not (executable.parent / "probe-count").exists()


@pytest.mark.parametrize(
    (
        "normal_passed",
        "detached_passed",
        "expected_continue",
        "expected_blocker",
    ),
    [
        (True, True, True, None),
        (True, False, False, "DETACHED_ENVIRONMENT_MISMATCH"),
        (False, True, False, "CONTROL_ENVIRONMENT_INVALID"),
        (False, False, False, "DIRECT_CODEX_PROVIDER_PATH_FAILED"),
    ],
    ids=(
        "normal-pass-detached-pass",
        "normal-pass-detached-fail",
        "normal-fail-detached-pass",
        "normal-fail-detached-fail",
    ),
)
def test_gate_zero_fake_direct_exec_control_result_matrix(
    monkeypatch: pytest.MonkeyPatch,
    normal_passed: bool,
    detached_passed: bool,
    expected_continue: bool,
    expected_blocker: str | None,
) -> None:
    def real_probe_forbidden(*_args, **_kwargs):
        raise AssertionError("Gate Zero matrix coverage must not invoke real Codex.")

    monkeypatch.setattr(
        connectivity_module,
        "_run_exec_connectivity_probe",
        real_probe_forbidden,
    )
    runner = _FakeDirectExecControlRunner(
        normal=normal_passed,
        detached=detached_passed,
    )

    decision = connectivity_module.classify_direct_exec_gate_zero(
        runner.run("normal"),
        runner.run("detached"),
    )

    assert runner.invocations == ["normal", "detached"]
    assert decision == {
        "normal_passed": normal_passed,
        "detached_passed": detached_passed,
        "can_continue": expected_continue,
        "blocker_code": expected_blocker,
    }


def test_gate_zero_environment_comparison_contains_only_keys_and_presence_booleans() -> None:
    secret = "sk-gate-zero-secret-value-must-not-appear"
    proxy = "http://owner:proxy-secret@127.0.0.1:9"
    normal_environment = {
        "HOME": "/safe/control-home",
        "OPENAI_API_KEY": secret,
        "HTTPS_PROXY": proxy,
        "NO_COLOR": "1",
    }
    detached_environment = {
        "HOME": "/safe/control-home",
        "OPENAI_API_KEY": secret,
        "GIT_TERMINAL_PROMPT": "0",
        "NO_COLOR": "1",
    }

    comparison = connectivity_module.safe_environment_shape_comparison(
        frozenset(normal_environment),
        frozenset(detached_environment),
    )

    assert comparison["matches"] is False
    assert comparison["normal_only"] == ["HTTPS_PROXY"]
    assert comparison["detached_only"] == ["GIT_TERMINAL_PROMPT"]
    assert comparison["presence"] == [
        {
            "key": "GIT_TERMINAL_PROMPT",
            "normal_present": False,
            "detached_present": True,
            "different": True,
        },
        {
            "key": "HOME",
            "normal_present": True,
            "detached_present": True,
            "different": False,
        },
        {
            "key": "HTTPS_PROXY",
            "normal_present": True,
            "detached_present": False,
            "different": True,
        },
        {
            "key": "NO_COLOR",
            "normal_present": True,
            "detached_present": True,
            "different": False,
        },
        {
            "key": "OPENAI_API_KEY",
            "normal_present": True,
            "detached_present": True,
            "different": False,
        },
    ]
    serialized = json.dumps(comparison, sort_keys=True)
    assert secret not in serialized
    assert proxy not in serialized
    assert "/safe/control-home" not in serialized
    assert all(
        set(item) == {
            "key",
            "normal_present",
            "detached_present",
            "different",
        }
        and type(item["normal_present"]) is bool
        and type(item["detached_present"]) is bool
        and type(item["different"]) is bool
        for item in comparison["presence"]
    )
    with pytest.raises(TypeError, match="key collections only"):
        connectivity_module.safe_environment_shape_comparison(
            normal_environment,  # type: ignore[arg-type]
            detached_environment,  # type: ignore[arg-type]
        )


def test_secret_output_is_redacted_and_executable_change_invalidates_match(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, executable, _ = _client(tmp_path, monkeypatch, mode="secret_output")
    with client:
        _signup(client)
        payload = _verify(client)
        rendered = json.dumps(payload)
        assert payload["readiness_state"] == "READY_FOR_REAL_RUN"
        assert "fixture-secret-token" not in rendered
        assert "sk-fixturesecret" not in rendered
        assert "/usr/local/private-fixture" not in rendered
        executable.write_text(executable.read_text() + "\n# executable identity changed\n")
        later = client.get(
            "/api/codex/setup/connectivity", params={"model_identifier": MODEL}
        ).json()
        assert later["readiness_state"] == "AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED"
        assert later["ready_for_real_run"] is False


def test_same_stat_executable_or_file_credential_replacement_invalidates_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, executable, _ = _client(tmp_path, monkeypatch)
    auth_file = tmp_path / "codex-home" / "auth.json"
    auth_file.write_text('{"owner":"A"}')
    with client:
        _signup(client)
        assert _verify(client)["ready_for_real_run"] is True

        executable_stat = executable.stat()
        executable.write_text(
            executable.read_text().replace(
                "executable-identity-marker-A", "executable-identity-marker-B"
            )
        )
        os.utime(
            executable,
            ns=(executable_stat.st_atime_ns, executable_stat.st_mtime_ns),
        )
        assert executable.stat().st_size == executable_stat.st_size
        replaced_executable = client.get(
            "/api/codex/setup/connectivity", params={"model_identifier": MODEL}
        ).json()
        assert replaced_executable["ready_for_real_run"] is False

        assert _verify(client)["ready_for_real_run"] is True
        auth_stat = auth_file.stat()
        auth_file.write_text('{"owner":"B"}')
        os.utime(auth_file, ns=(auth_stat.st_atime_ns, auth_stat.st_mtime_ns))
        assert auth_file.stat().st_size == auth_stat.st_size
        replaced_auth = client.get(
            "/api/codex/setup/connectivity", params={"model_identifier": MODEL}
        ).json()
        assert replaced_auth["ready_for_real_run"] is False


def test_cli_version_change_invalidates_ready_without_launcher_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, executable, _ = _client(tmp_path, monkeypatch)
    version_path = executable.with_suffix(".version")
    with client:
        _signup(client)
        first = _verify(client)
        assert first["ready_for_real_run"] is True

        version_path.write_text("codex-cli 0.145.0-connectivity-test")
        changed = client.get(
            "/api/codex/setup/connectivity", params={"model_identifier": MODEL}
        ).json()
        assert changed["readiness_state"] == "AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED"
        assert changed["ready_for_real_run"] is False
        assert changed["evidence_id"] is None


def test_npm_native_child_change_invalidates_executable_identity(tmp_path: Path) -> None:
    package_root = tmp_path / "node_modules" / "@openai" / "codex"
    launcher = package_root / "bin" / "codex.js"
    native = (
        package_root
        / "node_modules"
        / "@openai"
        / "codex-test-platform"
        / "vendor"
        / "test-target"
        / "bin"
        / "codex"
    )
    launcher.parent.mkdir(parents=True)
    native.parent.mkdir(parents=True)
    launcher.write_text(
        "#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then echo 'codex-cli fixture'; fi\n"
    )
    launcher.chmod(0o755)
    native.write_bytes(b"native-child-A")
    first = connectivity_module.executable_identity(str(launcher))

    native_stat = native.stat()
    native.write_bytes(b"native-child-B")
    os.utime(native, ns=(native_stat.st_atime_ns, native_stat.st_mtime_ns))
    assert native.stat().st_size == native_stat.st_size
    assert connectivity_module.executable_identity(str(launcher)) != first


def test_file_uri_absolute_paths_are_redacted_in_backend_and_ui() -> None:
    sanitized = sanitize_result_value(
        "file:///Users/owner/private/result.json file://localhost/private/tmp/result.json"
    )
    assert sanitized == (
        "[absolute file URI withheld] [absolute file URI withheld]"
    )
    javascript = (
        STATIC_COCKPIT_DIR / "vol12_static_mvp" / "twos_command_center.js"
    ).read_text()
    assert "file:\\/\\/" in javascript


def test_cli_not_installed_and_no_update_delete_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, executable, _ = _client(tmp_path, monkeypatch)
    executable.unlink()
    with client:
        _signup(client)
        result = client.get("/api/codex/setup/connectivity")
        assert result.json()["readiness_state"] == "CLI_NOT_INSTALLED"
        assert client.patch("/api/codex/setup/connectivity", json={}).status_code == 405
        assert client.delete("/api/codex/setup/connectivity").status_code == 405


def test_verified_timeout_envelope_is_not_reported_as_successful_execution() -> None:
    envelope = CodexResultEnvelope(
        envelope_id="envelope-timeout",
        owner_id=1,
        monitor_id=1,
        run_id=1,
        task_id=1,
        task_version=1,
        pack_id=1,
        pack_version=1,
        coding_assignment_id=1,
        coding_assignment_version=1,
        verification_assignment_id=2,
        verification_assignment_version=1,
        routing_snapshot_identity="a" * 64,
        source_snapshot_identity="b" * 64,
        requested_model_identifier=MODEL,
        actual_model_identifier="",
        terminal_status="timed_out",
        process_exit_code=None,
        final_response="Run timed out.",
        structured_handoff_json="{}",
        tests_summary_json="[]",
        changed_file_manifest_json="[]",
        diff_identity="c" * 64,
        coding_evidence_json='{"safe_summary":"no verified model execution"}',
        verification_evidence_json="{}",
        verification_verdict="unavailable",
        warnings_json="[]",
        limitations_json="[]",
        boundary_statements_json="{}",
        execution_duration_ms=302000,
        result_source="persisted_run",
        result_source_identity="d" * 64,
        process_evidence_identity="e" * 64,
        result_digest="f" * 64,
        integrity_state="VERIFIED",
        integrity_findings_json="[]",
        ingested_at=datetime(2026, 8, 3),
    )
    output = result_envelope_out(envelope)
    assert output["result_available"] is True
    assert output["result_integrity"] == "VERIFIED"
    assert output["execution_successful"] is False
    assert output["outcome_label"] == "Run timed out"
    assert output["actual_model_verified"] is False
    assert output["verification_result"]["verdict"] == "unavailable"
    assert output["accepted_source_result"] is False
    assert output["handoff_reconciliation"] == "BLOCKED"


def test_connectivity_ui_is_owner_triggered_truthful_and_progressively_disclosed() -> None:
    ui_root = Path(__file__).parents[1] / "static_cockpit" / "vol12_static_mvp"
    html = (ui_root / "twos_command_center.html").read_text(encoding="utf-8")
    javascript = (ui_root / "twos_command_center.js").read_text(encoding="utf-8")
    css = (ui_root / "styles.css").read_text(encoding="utf-8")

    for label in (
        "CLI installed",
        "CLI version",
        "Authentication method",
        "Authentication status",
        "Credential store",
        "Provider connectivity",
        "Requested model",
        "Resolved / effective model",
        "Last connectivity check",
        "Configured Run timeout",
        "Verify Codex Connection",
        "Advanced",
    ):
        assert label in html
    assert '<details id="setup-catalog-details"' in html
    assert '<details id="setup-catalog-details" open' not in html
    assert "does not contact the Provider" in html
    assert "a real Run's actual model still requires separate Run-local evidence" in html
    assert 'PROTOCOL_COMPATIBILITY_BLOCKED: "Protocol compatibility blocked"' in javascript
    assert '"Safe method: " + criticalMethod' in javascript
    assert '"Schema digest: "' in javascript
    assert '" Next Owner action: "' in javascript
    assert javascript.count("async function verifyCodexConnection()") == 1
    assert javascript.count('api("/api/codex/setup/verify-connection"') == 1
    assert (
        'elements.verifyCodexConnection.addEventListener("click", verifyCodexConnection)'
        in javascript
    )
    assert "Result available — Run timed out" in javascript
    assert "No verified actual model" in javascript
    assert "no verified model execution" in javascript
    assert "Verification unavailable" in javascript
    assert "no accepted source result" in javascript
    assert "Review Handoff: BLOCKED" in javascript
    assert "@media (max-width: 420px)" in css
    assert "Verify Applied Changes" in html
    connectivity_action = javascript.split(
        "async function verifyCodexConnection()",
        1,
    )[1].split("async function saveAndAssignCodex", 1)[0]
    assert '"/push-preflights"' not in connectivity_action
    assert '"/push-attempts"' not in connectivity_action
    assert "confirmPushToOriginMain" not in connectivity_action
