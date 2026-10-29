"""Bundled desktop service. Its stdout is a private pipe to the native launcher.

No credentials or setup URLs are written to logs. Executable code stays inside
the app bundle; only data, logs and isolated work products enter writable roots.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import stat
import sys
import threading
import time
import uuid
import traceback
import re

from scripts import twos_bootstrap as bootstrap
from . import __version__, INSTALLATION_COMPATIBLE_VERSIONS


def event(kind, **fields):
    print(json.dumps({"event": kind, **fields}), flush=True)


def failure_detail(exc, stage):
    """Only symbols and product source locations, never exception text/locals."""
    frames = []
    for frame in traceback.extract_tb(exc.__traceback__)[-8:]:
        name = Path(frame.filename).name
        if name.endswith('.py') and name.replace('_', '').replace('.', '').isalnum():
            frames.append({'file': name, 'line': frame.lineno})
    return {'stage': stage, 'exception_type': type(exc).__name__,
            'product_code': getattr(exc, 'code', None) if type(exc).__name__ in ('FirstRunError', 'MaintenanceError') else None,
            'frames': frames}


def build_identity():
    if getattr(sys, "frozen", False):
        try:
            value = json.loads((Path(sys.executable).parent.parent / 'source-provenance.json').read_text())
            return {key: value.get(key) for key in ('build_version', 'source_commit', 'source_input_sha256', 'self_iteration_test_artifact')}
        except (OSError, ValueError):
            return {'build_version': 'Unknown', 'source_commit': None}
    return {'build_version': 'development', 'source_commit': None}


def trusted_executable(path: Path) -> bool:
    try:
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or not os.access(resolved, os.X_OK):
            return False
        for item in (resolved, *resolved.parents):
            info = item.stat()
            system_applications = str(item) == "/Applications" and info.st_uid == 0 and info.st_gid == 80 and not info.st_mode & 0o002
            sticky_temporary = str(item) in ("/private/tmp", "/tmp") and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if info.st_mode & 0o022 and not system_applications and not sticky_temporary:
                return False
        return True
    except OSError:
        return False


def discover_codex(home: Path) -> str | None:
    # Official installed applications first; no credential stores are read here.
    candidates = [Path("/Applications") / name / "Contents/Resources/codex" for name in ("ChatGPT.app", "Codex.app")]
    candidates += [home / "Applications" / name / "Contents/Resources/codex" for name in ("ChatGPT.app", "Codex.app")]
    candidates += [root / name / "Contents/Resources/codex-cli/bin/codex"
                   for root in (Path('/Applications'), home / 'Applications')
                   for name in ('ChatGPT.app', 'Codex.app')]
    candidates += [home / ".npm-global/bin/codex", Path("/opt/homebrew/bin/codex"), Path("/usr/local/bin/codex")]
    return next((str(path.resolve()) for path in candidates if trusted_executable(path)), None)


def directories(home: Path, diagnostic_root: Path | None = None, environment_id: str | None = None):
    if environment_id is not None:
        if not re.fullmatch(r'env_[a-f0-9]{32}', environment_id):
            raise bootstrap.BootstrapError('DESKTOP_ENVIRONMENT_INVALID')
        base = (diagnostic_root / 'environments' if diagnostic_root else home / 'Library/Application Support/Tianma Work OS Environments') / environment_id
        return base / 'data', base / 'runtime', base / 'logs', base / 'projects'
    if diagnostic_root is not None:
        base = diagnostic_root
        return base / "data", base / "runtime", base / "logs", base / "projects"
    return (home / "Library/Application Support/Tianma Work OS Desktop",
            home / "Library/Caches/Tianma Work OS Desktop",
            home / "Library/Logs/Tianma Work OS Desktop",
            home / "Tianma Work OS Projects")


def installation(data, runtime, logs, sock):
    path = data / "installation.json"
    binding = dict(source_version=__version__, data_root=str(data), database_path=str(data / "twos.sqlite3"),
                   runtime_environment=str(Path(sys.prefix).resolve()), log_directory=str(logs), bind_host="127.0.0.1")
    if path.exists():
        saved = bootstrap.read_json(path)
        if isinstance(saved.get("source_version"), str) and saved["source_version"] in INSTALLATION_COMPATIBLE_VERSIONS:
            binding["source_version"] = saved["source_version"]
        if not bootstrap.INSTALLATION_ID_RE.fullmatch(str(saved.get("installation_id", ""))) or any(saved.get(key) != value for key, value in binding.items()):
            raise bootstrap.BootstrapError("DESKTOP_INSTALLATION_MISMATCH")
        if type(saved.get("port")) is not int or not 1 <= saved["port"] <= 65535:
            raise bootstrap.BootstrapError("DESKTOP_INSTALLATION_MISMATCH")
        return saved
    saved = dict(binding, installation_id="install_" + uuid.uuid4().hex, port=sock.getsockname()[1],
                 first_run_state="uninitialized", setup_completed_at=None)
    bootstrap.atomic_private_json(path, saved)
    return saved


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--diagnostic-root", type=Path, help="Isolated automated installer test data; never the Owner product environment")
    parser.add_argument("--environment-id", help="Native chooser's generated local environment identity")
    args = parser.parse_args(argv)
    os.umask(0o077)
    logging.disable(logging.CRITICAL)  # Only stable, non-secret diagnostic codes cross the native pipe.
    home = Path.home().resolve(strict=True)
    data, runtime, logs, projects = directories(home, args.diagnostic_root, args.environment_id)
    descriptor = None
    sock = None
    stage = 'storage_boundary'
    try:
        if os.geteuid() == 0:
            raise bootstrap.BootstrapError("DESKTOP_ROOT_UNSUPPORTED")
        for path in (data, runtime, logs):
            bootstrap.reject_symlink_components(path)
            bootstrap.prepare_data_root(path)
        bootstrap.validate_data_root_contents(data)
        descriptor = bootstrap.acquire_startup_lock(data / "startup.lock")
        stage = 'local_port'
        event("progress", message="Initializing your local workspace…")
        saved = bootstrap.read_json(data / "installation.json") if (data / "installation.json").exists() else {}
        port = saved.get("port", 0)
        if type(port) is not int or not 0 <= port <= 65535:
            raise bootstrap.BootstrapError("DESKTOP_INSTALLATION_MISMATCH")
        try:
            sock = bootstrap.reserve_port(port)
        except bootstrap.BootstrapError as exc:
            if isinstance(exc.__cause__, PermissionError):
                raise bootstrap.BootstrapError("DESKTOP_NETWORK_DENIED") from exc
            raise bootstrap.BootstrapError("DESKTOP_PORT_OCCUPIED") from exc
        config = installation(data, runtime, logs, sock)
        stage = 'runtime_environment'
        # Clear caller-supplied application, Python, Git and provider configuration.
        preserved = {k: os.environ[k] for k in ("HOME", "TMPDIR", "LANG", "LC_CTYPE", "USER", "LOGNAME") if k in os.environ}
        preserved["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin:" + str(home / ".npm-global/bin")
        os.environ.clear()
        os.environ.update(preserved)
        env = bootstrap.child_environment(Path(__file__).resolve().parents[1], data, runtime, logs, config)
        env["TWOS_RUNTIME_ENVIRONMENT"] = config["runtime_environment"]
        env["TWOS_MANAGED_WORKSPACE_ROOT"] = str(projects)
        preferences = args.diagnostic_root if args.diagnostic_root else home / 'Library/Application Support/Tianma Work OS Preferences'
        bootstrap.reject_symlink_components(preferences)
        bootstrap.prepare_data_root(preferences)
        env['TWOS_UI_PREFERENCE_PATH'] = str(preferences / 'ui-preference.json')
        codex = discover_codex(home)
        if codex:
            env["TWOS_CODEX_EXECUTABLE"] = codex
        os.environ.update(env)
        stage = 'module_import'
        event('phase', stage=stage)
        import uvicorn
        from .app import create_app
        stage = 'application_initialization'
        event('phase', stage=stage)
        try:
            app = create_app()
        except Exception as exc:
            from .first_run import FirstRunError
            if not isinstance(exc, FirstRunError) or exc.code != 'WORKSPACE_IDENTITY_CHANGED':
                raise
            event('diagnostic', **failure_detail(exc, stage))
            from .config import get_settings
            from .workspace_recovery import recovery_app
            app = recovery_app(get_settings())
            event('phase', stage='workspace_owner_review')
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=config["port"], access_log=False,
                                             log_config=None, loop="asyncio", http="h11", ws="none", timeout_graceful_shutdown=8))

        def report_ready():
            for _ in range(1200):
                if server.should_exit:
                    return
                if server.started:
                    token_path = data / "setup-authorization.txt"
                    token = bootstrap.read_setup_authorization(token_path) if token_path.exists() else ""
                    entry = '/twos' if getattr(app.state, 'workspace_recovery', False) else '/projects'
                    # Restricted recovery apps expose only the historical recovery entry.
                    if not any(getattr(route,'path',None)=='/projects' for route in app.routes): entry='/twos'
                    event("ready", url=f"http://127.0.0.1:{config['port']}{entry}", setup=token,
                          version=__version__, codex=bool(codex))
                    return
                time.sleep(.1)
            event("error", code="DESKTOP_STARTUP_TIMEOUT")
            server.should_exit = True

        def parent_watch():
            # EOF from the native owner is also graceful shutdown after a launcher crash.
            sys.stdin.buffer.read()
            server.should_exit = True

        threading.Thread(target=report_ready, daemon=True).start()
        threading.Thread(target=parent_watch, daemon=True).start()
        stage = 'server_listen'
        event('phase', stage=stage)
        server.run(sockets=[sock])
        event("stopped")
        return 0
    except Exception as exc:
        event('diagnostic', **failure_detail(exc, stage))
        known = str(exc) if isinstance(exc, bootstrap.BootstrapError) else ""
        code = known if known.startswith("DESKTOP_") else "DESKTOP_STORAGE_UNAVAILABLE" if isinstance(exc, (OSError, bootstrap.BootstrapError)) else "DESKTOP_RUNTIME_FAILED"
        event("error", code=code)
        return 1
    finally:
        if sock is not None:
            sock.close()
        if descriptor is not None:
            os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
