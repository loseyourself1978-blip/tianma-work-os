"""Passive tool explanations and explicit selection from trusted local candidates.

No import, diagnosis or candidate enumeration launches a process, reads a
credential store, changes settings, or makes a provider request.
"""
from dataclasses import replace
import json
from pathlib import Path

from .desktop import trusted_executable
from .result_intake import canonical_sha256


def local_model_catalog():
    """Read only advertised model IDs from Codex's fixed, non-auth cache.

    This is configuration guidance, never readiness or invocation evidence.
    No process, provider request, credential file or directory traversal occurs.
    """
    path = Path.home() / '.codex' / 'models_cache.json'
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            return []
        value = json.loads(path.read_text())
        import re
        return sorted({m['slug'] for m in value.get('models', []) if isinstance(m, dict)
                       and m.get('visibility') == 'list' and isinstance(m.get('slug'), str)
                       and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}', m['slug'])})
    except (OSError, ValueError, TypeError):
        return []


def candidates(settings):
    home = Path.home()
    paths = [Path(settings.codex_executable)] if settings.codex_executable else []
    paths += [root / name / "Contents/Resources/codex"
              for root in (Path('/Applications'), home / 'Applications')
              for name in ('Codex.app', 'ChatGPT.app')]
    paths += [root / name / "Contents/Resources/codex-cli/bin/codex"
              for root in (Path('/Applications'), home / 'Applications')
              for name in ('Codex.app', 'ChatGPT.app')]
    paths += [home / '.npm-global/bin/codex', Path('/opt/homebrew/bin/codex'), Path('/usr/local/bin/codex')]
    forbidden = [Path(p).resolve(strict=False) for p in
                 (settings.source_repo, settings.worktree_root, settings.codex_spool_root, *settings.authorized_workspace_roots)]
    result = []
    seen = set()
    for path in paths:
        if not trusted_executable(path):
            continue
        real = path.resolve(strict=True)
        if real in seen or any(real.is_relative_to(root) for root in forbidden):
            continue
        seen.add(real)
        st = real.stat()
        identity = canonical_sha256([str(real), st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_mode])
        result.append({'id': identity, 'path': str(real), 'label': str(path)})
    return result


def selected_settings(settings, identity):
    candidate = next((item for item in candidates(settings) if item['id'] == identity), None)
    if candidate is None:
        raise ValueError('TOOL_SELECTION_CHANGED: The selected trusted tool is unavailable or changed. Reopen Tool Setup and choose again.')
    return replace(settings, codex_executable=candidate['path'])


def saved_settings(session, settings, owner_id):
    from .guided_delivery import latest_configuration
    try:
        row = latest_configuration(session, owner_id, confirmed=True, settings=settings)
    except FileNotFoundError:
        # Keep the caller's existing missing-repository gate and sanitized
        # explanation. Tool lookup must not turn that condition into HTTP 500.
        return settings
    if row is not None:
        snapshot = json.loads(row.snapshot_json)
        # Old configurations keep the existing discovery policy. An explicit
        # selection is durable and never silently falls back if it disappears.
        if snapshot.get('explicit_executable_selection') is True:
            return replace(settings, codex_executable=snapshot['executable'])
    return settings


def diagnosis(row, settings):
    from .guided_delivery import verification_binding
    from .codex_connectivity import executable_identity, _file_content_identity
    snapshot = json.loads(row.snapshot_json) if row is not None else {}
    reasons = []
    executable = snapshot.get('executable')
    if executable and not Path(executable).is_file():
        reasons.append({'code': 'EXECUTABLE_MISSING', 'message': 'The saved Codex executable is no longer at its saved location. Choose a trusted installed tool.'})
    elif executable and executable_identity(executable, cli_version=snapshot.get('cli_version', '')) != snapshot.get('executable_identity'):
        reasons.append({'code': 'EXECUTABLE_CHANGED', 'message': 'The saved executable identity changed. Review this tool and explicitly check readiness for future runs.'})
    old_verifier = snapshot.get('verification') or {}
    try:
        current_verifier = verification_binding(settings)
    except (ValueError, OSError):
        current_verifier = None
        reasons.append({'code': 'VERIFIER_UNAVAILABLE', 'message': 'The configured independent verifier is unavailable. Restore the supported installation or contact its maintainer.'})
    changed = bool(old_verifier and (current_verifier != old_verifier or any(
        _file_content_identity(Path(f['path'])) != f['identity'] for f in old_verifier.get('files', []))))
    if changed and current_verifier is not None:
        reasons.append({'code': 'VERIFIER_CHANGED', 'message': 'The independent verifier differs from the saved configuration. Confirm the current verifier for future runs before checking readiness.'})
    return {'configuration_saved': bool(row and row.confirmed_at), 'saved_executable': executable,
            'reasons': reasons, 'verifier_changed': changed,
            'verifier_available': current_verifier is not None,
            'verifier_digest': canonical_sha256(current_verifier) if current_verifier else None,
            'verifier_files': [f['path'] for f in (current_verifier or {}).get('files', [])],
            'scope': str(settings.source_repo.resolve(strict=False)),
            'provider_request_performed': False, 'historical_delivery_unchanged': True}
