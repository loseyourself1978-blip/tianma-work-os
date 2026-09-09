from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from scripts import twos_bootstrap


ROOT = Path(__file__).resolve().parents[1]
USERNAME = "owner-first-run"


def available_local_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def wait_for_process_exit(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


def terminate_owned_process(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    if wait_for_process_exit(pid, 20):
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    assert wait_for_process_exit(pid, 5), f"owned runtime PID {pid} did not exit"


def source_snapshot(path: Path) -> dict[str, tuple[int, str]]:
    snapshot: dict[str, tuple[int, str]] = {}
    for item in sorted(path.rglob("*")):
        relative = str(item.relative_to(path))
        if item.is_symlink():
            snapshot[relative] = (0, f"symlink:{os.readlink(item)}")
        elif item.is_file():
            snapshot[relative] = (
                item.stat().st_mode & 0o777,
                hashlib.sha256(item.read_bytes()).hexdigest(),
            )
        elif item.is_dir():
            snapshot[relative] = (item.stat().st_mode & 0o777, "directory")
    return snapshot


def clean_source_copy(destination: Path) -> None:
    ignored = shutil.ignore_patterns(
        ".git",
        ".venv",
        ".pytest_cache",
        "__pycache__",
        "*.pyc",
        "twos_runtime.sqlite3",
    )
    shutil.copytree(ROOT, destination, ignore=ignored)


class ControlledBootstrapProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -signal.SIGTERM

    def kill(self) -> None:
        self.returncode = -signal.SIGKILL

    def wait(self, timeout: float | None = None) -> int:
        assert timeout is not None
        assert self.returncode is not None
        return self.returncode

    def send_signal(self, signum: int) -> None:
        self.returncode = -signum


@pytest.mark.parametrize("outcome", ["success", "blocked", "help"])
def test_bootstrap_entrypoint_restores_caller_umask(tmp_path, monkeypatch, outcome):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    arguments = [
        "--check", "--source-root", str(ROOT), "--python", sys.executable,
        "--data-root", str(tmp_path / "data"),
        "--runtime-root", str(tmp_path / "runtime"),
        "--log-root", str(tmp_path / "logs"),
    ]
    if outcome == "blocked":
        arguments[arguments.index("--data-root") + 1] = str(ROOT / "unsafe-data")
    previous = os.umask(0o027)
    try:
        if outcome == "help":
            with pytest.raises(SystemExit) as raised:
                twos_bootstrap.main(["--help"])
            assert raised.value.code == 0
        else:
            assert twos_bootstrap.main(arguments) == (0 if outcome == "success" else 2)
        probe = tmp_path / "caller-owned-file"
        probe.write_text("non-sensitive permission probe")
        assert probe.stat().st_mode & 0o777 == 0o640
        assert not (tmp_path / "data").exists()
        assert not (tmp_path / "runtime").exists()
    finally:
        os.umask(previous)


def test_bootstrap_refuses_root_and_reports_unsupported_python(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(twos_bootstrap.os, "geteuid", lambda: 0)
    assert twos_bootstrap.main(["--check"]) == 2
    assert "must not be started as root" in capsys.readouterr().err

    monkeypatch.setattr(twos_bootstrap.os, "geteuid", lambda: 501)
    monkeypatch.setattr(twos_bootstrap, "python_version", lambda _path: (3, 10, 9))
    with pytest.raises(twos_bootstrap.BootstrapError) as raised:
        twos_bootstrap.select_python("/unsupported/python")
    assert "requires Python 3.11, 3.12, or 3.13" in str(raised.value)


def test_shell_launcher_finds_versioned_python_and_reports_when_none_exists(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source with spaces"
    source.mkdir()
    launcher = source / "start-twos"
    shutil.copy2(ROOT / "start-twos", launcher)
    launcher.chmod(0o700)
    tool_bin = tmp_path / "bin"
    tool_bin.mkdir()
    dirname = shutil.which("dirname")
    assert dirname is not None
    (tool_bin / "dirname").symlink_to(dirname)
    versioned_python = tool_bin / "python3.11"
    versioned_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\"\n",
        encoding="utf-8",
    )
    versioned_python.chmod(0o700)
    environment = {"PATH": str(tool_bin)}

    selected = subprocess.run(
        [str(launcher), "--check"],
        cwd=source,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5,
        check=False,
    )
    assert selected.returncode == 0
    assert selected.stdout.splitlines() == [
        str(source / "scripts" / "twos_bootstrap.py"),
        "--source-root",
        str(source),
        "--check",
    ]

    versioned_python.unlink()
    missing = subprocess.run(
        [str(launcher), "--check"],
        cwd=source,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5,
        check=False,
    )
    assert missing.returncode == 2
    assert "Python 3 is unavailable" in missing.stderr


def test_data_root_traversal_and_symlink_boundaries_are_rejected_without_mutation(
    tmp_path: Path,
) -> None:
    source = ROOT.resolve()
    protected = tmp_path / "protected-owner-data"
    protected.mkdir(mode=0o700)
    sentinel = protected / "owner-note.txt"
    sentinel.write_text("preserve exactly\n", encoding="utf-8")

    root_link = tmp_path / "linked-data-root"
    root_link.symlink_to(protected, target_is_directory=True)
    component_target = tmp_path / "component-target"
    component_target.mkdir(mode=0o700)
    component_link = tmp_path / "linked-parent"
    component_link.symlink_to(component_target, target_is_directory=True)
    nested_data_root = component_link / "new-data-root"
    missing_root_target = tmp_path / "missing-root-target"
    dangling_root_link = tmp_path / "dangling-data-root"
    dangling_root_link.symlink_to(missing_root_target, target_is_directory=True)
    missing_component_target = tmp_path / "missing-component-target"
    dangling_component_link = tmp_path / "dangling-parent"
    dangling_component_link.symlink_to(
        missing_component_target,
        target_is_directory=True,
    )
    nested_dangling_data_root = dangling_component_link / "new-data-root"
    traversing_data_root = tmp_path / "absent-parent" / ".." / "new-data-root"
    before = source_snapshot(tmp_path)

    for candidate in (
        traversing_data_root,
        root_link,
        nested_data_root,
        dangling_root_link,
        nested_dangling_data_root,
    ):
        with pytest.raises(twos_bootstrap.BootstrapError):
            twos_bootstrap.validate_installation_path(
                candidate,
                source,
                "The TWOS data root",
            )

    assert source_snapshot(tmp_path) == before
    assert sentinel.read_text(encoding="utf-8") == "preserve exactly\n"
    assert not nested_data_root.exists()
    assert not missing_root_target.exists()
    assert not missing_component_target.exists()
    assert not nested_dangling_data_root.exists()
    assert not (tmp_path / "new-data-root").exists()


def test_bootstrap_path_port_lock_and_environment_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ROOT.resolve()
    with pytest.raises(twos_bootstrap.BootstrapError):
        twos_bootstrap.validate_installation_path(source.parent, source, "Data root")

    class OccupiedSocket:
        def setsockopt(self, *_args: object) -> None:
            return None

        def bind(self, *_args: object) -> None:
            raise OSError("occupied")

        def close(self) -> None:
            return None

    monkeypatch.setattr(twos_bootstrap.socket, "socket", lambda *_args: OccupiedSocket())
    with pytest.raises(twos_bootstrap.BootstrapError) as port_error:
        twos_bootstrap.available_port(18080)
    assert "unavailable" in str(port_error.value)

    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    lock = data / "startup.lock"
    first = twos_bootstrap.acquire_startup_lock(lock)
    try:
        with pytest.raises(twos_bootstrap.BootstrapError):
            twos_bootstrap.acquire_startup_lock(lock)
    finally:
        os.close(first)

    installation = {"installation_id": "install_" + "a" * 32, "port": 18080}
    monkeypatch_environment = {
        "TWOS_DATABASE_PATH": "/normal/data.sqlite3",
        "OPENAI_API_KEY": "must-not-survive",
        "AWS_SECRET_ACCESS_KEY": "must-not-survive",
        "CODEX_HOME": "/normal/codex-credentials",
        "CLAUDE_API_KEY": "must-not-survive",
        "GH_TOKEN": "must-not-survive",
        "GH_ENTERPRISE_TOKEN": "must-not-survive",
        "PYTHONPATH": "/must/not/survive",
        "PYTHONHOME": "/must/not/survive",
        "VIRTUAL_ENV": "/must/not/survive",
        "PATH": os.environ.get("PATH", ""),
    }
    original = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(monkeypatch_environment)
        child = twos_bootstrap.child_environment(
            source,
            data,
            tmp_path / "runtime",
            tmp_path / "logs",
            installation,
        )
    finally:
        os.environ.clear()
        os.environ.update(original)
    assert child["TWOS_DATABASE_PATH"] == str(data / "twos.sqlite3")
    assert "OPENAI_API_KEY" not in child
    assert child["TWOS_BIND_HOST"] == "127.0.0.1"
    assert child["PYTHONDONTWRITEBYTECODE"] == "1"
    assert child["TWOS_SESSION_COOKIE_NAME"].endswith(installation["installation_id"])
    for inherited in (
        "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "AWS_SECRET_ACCESS_KEY",
        "CODEX_HOME", "CLAUDE_API_KEY", "GH_TOKEN", "GH_ENTERPRISE_TOKEN",
    ):
        assert inherited not in child


def test_local_health_probe_cannot_be_redirected_through_inherited_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"healthy","database":"ok"}')

        def log_message(self, *_args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
            monkeypatch.setenv(name, "http://127.0.0.1:1")
        monkeypatch.setenv("no_proxy", "")
        monkeypatch.setenv("NO_PROXY", "")
        payload = twos_bootstrap.health_payload(
            f"http://127.0.0.1:{server.server_port}/api/health"
        )
        assert payload == {"status": "healthy", "database": "ok"}
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


def test_browser_opens_only_after_truthful_health_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "data"
    port = available_local_port()
    process = ControlledBootstrapProcess(2_000_001)
    events: list[tuple[str, object]] = []
    monkeypatch.setattr(twos_bootstrap.os, "geteuid", lambda: 501)
    monkeypatch.setattr(
        twos_bootstrap,
        "select_python",
        lambda _value=None: (sys.executable, (3, 12, 0)),
    )

    def prepared_runtime(
        _source: Path,
        _runtime: Path,
        _python: str,
        _version: tuple[int, int, int],
        log_path: Path,
        _refresh: bool,
    ) -> Path:
        log_path.touch(mode=0o600)
        return Path(sys.executable)

    def healthy_payload(url: str, timeout: float = 2.0) -> dict[str, object]:
        assert url == f"http://127.0.0.1:{port}/api/health"
        assert timeout == 2.0
        events.append(("health", url))
        installation = json.loads(
            (data / "installation.json").read_text(encoding="utf-8")
        )
        return {
            "status": "healthy",
            "database": "ok",
            "version": twos_bootstrap.APP_VERSION,
            "schema": twos_bootstrap.LATEST_SCHEMA,
            "bind_host": "127.0.0.1",
            "installation_id": installation["installation_id"],
        }

    def open_browser(url: str, new: int = 0) -> bool:
        events.append(("browser", (url, new)))
        return True

    monkeypatch.setattr(twos_bootstrap, "ensure_runtime_environment", prepared_runtime)
    monkeypatch.setattr(
        twos_bootstrap.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(twos_bootstrap, "health_payload", healthy_payload)
    monkeypatch.setattr(twos_bootstrap.webbrowser, "open", open_browser)

    result = twos_bootstrap.main(
        [
            "--source-root",
            str(ROOT),
            "--data-root",
            str(data),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--log-root",
            str(tmp_path / "logs"),
            "--port",
            str(port),
            "--python",
            sys.executable,
            "--detach",
        ]
    )

    assert result == 0
    assert events == [
        ("health", f"http://127.0.0.1:{port}/api/health"),
        ("browser", (f"http://127.0.0.1:{port}/twos", 2)),
    ]
    assert process.terminated is False


def test_browser_does_not_open_when_health_fails_and_owned_child_is_reaped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = tmp_path / "data"
    port = available_local_port()
    process = ControlledBootstrapProcess(2_000_002)
    events: list[str] = []
    monkeypatch.setattr(twos_bootstrap.os, "geteuid", lambda: 501)
    monkeypatch.setattr(
        twos_bootstrap,
        "select_python",
        lambda _value=None: (sys.executable, (3, 12, 0)),
    )

    def prepared_runtime(
        _source: Path,
        _runtime: Path,
        _python: str,
        _version: tuple[int, int, int],
        log_path: Path,
        _refresh: bool,
    ) -> Path:
        log_path.touch(mode=0o600)
        return Path(sys.executable)

    def unavailable_health(_url: str, timeout: float = 2.0) -> None:
        assert timeout == 2.0
        events.append("health")
        return None

    def unexpected_browser(_url: str, new: int = 0) -> bool:
        events.append(f"browser:{new}")
        return True

    monkeypatch.setattr(twos_bootstrap, "ensure_runtime_environment", prepared_runtime)
    monkeypatch.setattr(
        twos_bootstrap.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(twos_bootstrap, "health_payload", unavailable_health)
    monkeypatch.setattr(twos_bootstrap.webbrowser, "open", unexpected_browser)

    result = twos_bootstrap.main(
        [
            "--source-root",
            str(ROOT),
            "--data-root",
            str(data),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--log-root",
            str(tmp_path / "logs"),
            "--port",
            str(port),
            "--python",
            sys.executable,
            "--detach",
            "--health-timeout",
            "0.01",
        ]
    )

    assert result == 2
    assert events == ["health"]
    assert process.terminated is True
    assert not (data / "runtime.pid").exists()
    assert "did not reach a truthful healthy state" in capsys.readouterr().err
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", port))


def test_bare_python_resolution_and_special_control_files_are_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        twos_bootstrap.shutil,
        "which",
        lambda value: "/opt/local/bin/python3.11" if value == "python3.11" else None,
    )
    monkeypatch.setattr(
        twos_bootstrap,
        "python_version",
        lambda value: (3, 11, 9) if value == "/opt/local/bin/python3.11" else None,
    )
    executable, version = twos_bootstrap.select_python("python3.11")
    assert executable == "/opt/local/bin/python3.11"
    assert version[:2] == (3, 11)

    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    lock_fifo = data / "startup.lock"
    os.mkfifo(lock_fifo)
    with pytest.raises(twos_bootstrap.BootstrapError, match="startup-lock path is unsafe"):
        twos_bootstrap.acquire_startup_lock(lock_fifo)
    pid_fifo = data / "runtime.pid"
    os.mkfifo(pid_fifo)
    with pytest.raises(twos_bootstrap.BootstrapError, match="PID file is unsafe"):
        twos_bootstrap.configured_live_pid(pid_fifo)

    config_fifo = data / "installation.json"
    os.mkfifo(config_fifo)
    with pytest.raises(
        twos_bootstrap.BootstrapError,
        match="installation configuration is unsafe",
    ):
        twos_bootstrap.read_json(config_fifo)

    setup_fifo = data / "setup-authorization.txt"
    os.mkfifo(setup_fifo)
    with pytest.raises(
        twos_bootstrap.BootstrapError,
        match="setup authorization file is unsafe",
    ):
        twos_bootstrap.read_setup_authorization(setup_fifo)

    log_fifo = data / "runtime.log"
    os.mkfifo(log_fifo)
    with pytest.raises(
        twos_bootstrap.BootstrapError,
        match="runtime log path is unsafe",
    ):
        twos_bootstrap.append_log(log_fifo, "must not block")

    victim = data / "victim.txt"
    victim.write_text("preserve\n", encoding="utf-8")
    victim.chmod(0o600)
    for control_name, operation in (
        ("config-link.json", lambda path: twos_bootstrap.read_json(path)),
        ("setup-link.txt", lambda path: twos_bootstrap.read_setup_authorization(path)),
        ("pid-link", lambda path: twos_bootstrap.write_pid(path, 12345)),
        ("log-link", lambda path: twos_bootstrap.append_log(path, "must not follow")),
    ):
        control_path = data / control_name
        control_path.symlink_to(victim)
        with pytest.raises(twos_bootstrap.BootstrapError):
            operation(control_path)
    assert victim.read_text(encoding="utf-8") == "preserve\n"

    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    missing_external_venv = tmp_path / "missing-external-venv"
    (runtime / "venv").symlink_to(
        missing_external_venv,
        target_is_directory=True,
    )
    monkeypatch.setattr(
        twos_bootstrap.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("no subprocess may follow a dangling runtime symlink")
        ),
    )
    with pytest.raises(
        twos_bootstrap.BootstrapError,
        match="runtime environment path is unsafe",
    ):
        twos_bootstrap.ensure_runtime_environment(
            ROOT.resolve(),
            runtime,
            sys.executable,
            (3, 12, 0),
            tmp_path / "runtime.log",
            False,
        )
    assert not missing_external_venv.exists()


def test_real_dependency_install_failure_is_redacted_and_does_not_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ROOT.resolve()
    runtime = tmp_path / "runtime"
    logs = tmp_path / "logs"
    logs.mkdir(mode=0o700)
    log_path = logs / "runtime.log"
    commands: list[list[str]] = []

    def failed_install(
        command: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        commands.append([str(value) for value in command])
        if command[1:3] == ["-m", "venv"]:
            (runtime / "venv" / "bin").mkdir(parents=True)
            (runtime / "venv" / "bin" / "python").touch(mode=0o700)
            return subprocess.CompletedProcess(command, 0, stdout="created")
        assert command[1:4] == ["-m", "pip", "install"]
        return subprocess.CompletedProcess(
            command,
            17,
            stdout="private-index-token-must-not-be-persisted",
        )

    monkeypatch.setattr(twos_bootstrap.subprocess, "run", failed_install)
    before_source = source_snapshot(source)
    with pytest.raises(
        twos_bootstrap.BootstrapError,
        match="dependencies could not be installed",
    ):
        twos_bootstrap.ensure_runtime_environment(
            source,
            runtime,
            sys.executable,
            (3, 12, 0),
            log_path,
            False,
        )
    assert len(commands) == 2
    assert commands[0][1:3] == ["-m", "venv"]
    assert Path(commands[1][0]) == runtime / "venv" / "bin" / "python"
    persisted_log = log_path.read_text(encoding="utf-8")
    assert "status 17" in persisted_log
    assert "private-index-token" not in persisted_log
    assert not (runtime / "dependency-state.json").exists()
    assert source_snapshot(source) == before_source


def test_dependency_failure_is_truthful_and_never_spawns_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(twos_bootstrap.os, "geteuid", lambda: 501)
    monkeypatch.setattr(
        twos_bootstrap, "select_python", lambda _value=None: (sys.executable, (3, 12, 0))
    )
    monkeypatch.setattr(
        twos_bootstrap,
        "ensure_runtime_environment",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            twos_bootstrap.BootstrapError(
                "Dependency installation failed inside the isolated runtime environment."
            )
        ),
    )
    monkeypatch.setattr(
        twos_bootstrap.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("runtime must not spawn after dependency failure")
        ),
    )
    result = twos_bootstrap.main(
        [
            "--source-root",
            str(ROOT),
            "--data-root",
            str(tmp_path / "data"),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--log-root",
            str(tmp_path / "logs"),
            "--python",
            sys.executable,
            "--no-browser",
        ]
    )
    assert result == 2
    assert "Dependency installation failed" in capsys.readouterr().err
    assert not list((tmp_path / "data").glob("runtime.pid"))


def test_post_spawn_handoff_failure_reaps_exact_child_and_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeProcess:
        pid = 987654

        def __init__(self) -> None:
            self.returncode: int | None = None
            self.terminated = False

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -signal.SIGTERM

        def kill(self) -> None:
            self.returncode = -signal.SIGKILL

        def wait(self, timeout: float | None = None) -> int:
            assert timeout is not None
            assert self.returncode is not None
            return self.returncode

        def send_signal(self, signum: int) -> None:
            self.returncode = -signum

    process = FakeProcess()
    monkeypatch.setattr(twos_bootstrap.os, "geteuid", lambda: 501)
    monkeypatch.setattr(
        twos_bootstrap, "select_python", lambda _value=None: (sys.executable, (3, 12, 0))
    )

    def prepared_runtime(
        _source: Path,
        _runtime: Path,
        _python: str,
        _version: tuple[int, int, int],
        log_path: Path,
        _refresh: bool,
    ) -> Path:
        log_path.touch(mode=0o600)
        return Path(sys.executable)

    monkeypatch.setattr(
        twos_bootstrap,
        "ensure_runtime_environment",
        prepared_runtime,
    )
    monkeypatch.setattr(twos_bootstrap.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        twos_bootstrap,
        "wait_for_health",
        lambda *_args, **_kwargs: {"status": "healthy", "database": "ok"},
    )
    monkeypatch.setattr(
        twos_bootstrap,
        "append_log",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("log projection failed")),
    )
    data = tmp_path / "data"
    result = twos_bootstrap.main(
        [
            "--source-root",
            str(ROOT),
            "--data-root",
            str(data),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--log-root",
            str(tmp_path / "logs"),
            "--python",
            sys.executable,
            "--detach",
            "--no-browser",
        ]
    )
    assert result == 2
    assert process.terminated is True
    assert not (data / "runtime.pid").exists()


def test_interrupted_startup_forwards_signal_reaps_child_and_restores_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeProcess:
        pid = 987655

        def __init__(self) -> None:
            self.returncode: int | None = None
            self.signals: list[int] = []

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.signals.append(signal.SIGTERM)
            self.returncode = -signal.SIGTERM

        def kill(self) -> None:
            self.signals.append(signal.SIGKILL)
            self.returncode = -signal.SIGKILL

        def wait(self, timeout: float | None = None) -> int:
            assert timeout is not None
            assert self.returncode is not None
            return self.returncode

        def send_signal(self, signum: int) -> None:
            self.signals.append(signum)
            self.returncode = -signum

    process = FakeProcess()
    monkeypatch.setattr(twos_bootstrap.os, "geteuid", lambda: 501)
    monkeypatch.setattr(
        twos_bootstrap, "select_python", lambda _value=None: (sys.executable, (3, 12, 0))
    )

    def prepared_runtime(
        _source: Path,
        _runtime: Path,
        _python: str,
        _version: tuple[int, int, int],
        log_path: Path,
        _refresh: bool,
    ) -> Path:
        log_path.touch(mode=0o600)
        return Path(sys.executable)

    def interrupt_startup(*_args: object, **_kwargs: object) -> dict[str, str]:
        signal.raise_signal(signal.SIGTERM)
        raise twos_bootstrap.BootstrapError("startup interrupted")

    monkeypatch.setattr(twos_bootstrap, "ensure_runtime_environment", prepared_runtime)
    monkeypatch.setattr(twos_bootstrap.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(twos_bootstrap, "wait_for_health", interrupt_startup)
    watched_signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous = {signum: signal.getsignal(signum) for signum in watched_signals}
    data = tmp_path / "data"
    result = twos_bootstrap.main(
        [
            "--source-root",
            str(ROOT),
            "--data-root",
            str(data),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--log-root",
            str(tmp_path / "logs"),
            "--python",
            sys.executable,
            "--detach",
            "--no-browser",
        ]
    )
    assert result == 2
    assert process.signals == [signal.SIGTERM]
    assert process.poll() == -signal.SIGTERM
    assert not (data / "runtime.pid").exists()
    assert {signum: signal.getsignal(signum) for signum in watched_signals} == previous


def test_foreign_nonempty_data_root_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = tmp_path / "foreign-data"
    data.mkdir(mode=0o700)
    marker = data / "owner-content.txt"
    marker.write_text("preserve\n", encoding="utf-8")
    before_mode = data.stat().st_mode & 0o777
    monkeypatch.setattr(twos_bootstrap.os, "geteuid", lambda: 501)
    result = twos_bootstrap.main(
        [
            "--source-root",
            str(ROOT),
            "--data-root",
            str(data),
            "--runtime-root",
            str(tmp_path / "runtime"),
            "--log-root",
            str(tmp_path / "logs"),
            "--python",
            sys.executable,
            "--no-browser",
        ]
    )
    assert result == 2
    assert marker.read_text(encoding="utf-8") == "preserve\n"
    assert data.stat().st_mode & 0o777 == before_mode
    assert not (tmp_path / "runtime").exists()
    assert not (tmp_path / "logs").exists()


def test_canonical_bootstrap_real_http_first_run_and_restart(tmp_path: Path) -> None:
    source = tmp_path / "fresh-source"
    clean_source_copy(source)
    assert not (source / ".venv").exists()
    before_source = source_snapshot(source)

    empty_home = tmp_path / "empty-home"
    empty_home.mkdir(mode=0o700)
    data = tmp_path / "fresh-data"
    runtime = tmp_path / "runtime"
    logs = tmp_path / "logs"
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    assert not data.exists()
    assert list(empty_home.iterdir()) == []
    assert list(workspace.iterdir()) == []
    port = available_local_port()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("TWOS_")
        and not any(
            key.startswith(prefix)
            for prefix in twos_bootstrap.SENSITIVE_CHILD_PREFIXES
        )
        and key not in twos_bootstrap.PYTHON_INJECTION_VARIABLES
    }
    environment["HOME"] = str(empty_home)
    password = "test-" + secrets.token_urlsafe(32)
    command = [
        str(source / "start-twos"),
        "--data-root",
        str(data),
        "--runtime-root",
        str(runtime),
        "--log-root",
        str(logs),
        "--port",
        str(port),
        "--detach",
        "--no-browser",
        "--health-timeout",
        "90",
    ]
    assert "--python" not in command
    first_pid: int | None = None
    second_pid: int | None = None
    try:
        launched = subprocess.run(
            command,
            cwd=source,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=600,
            check=False,
        )
        assert launched.returncode == 0, launched.stderr
        output_lines = launched.stdout.splitlines()
        first_pid = int(next(line.split(":", 1)[1] for line in output_lines if line.startswith("Runtime PID:")))
        setup_code = next(
            line.split(":", 1)[1].strip()
            for line in output_lines
            if line.startswith("Setup authorization code:")
        )
        base_url = f"http://127.0.0.1:{port}"
        duplicate = subprocess.run(
            command,
            cwd=source,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
        assert duplicate.returncode == 2
        assert "already running for this data root" in duplicate.stderr
        with httpx.Client(
            base_url=base_url, follow_redirects=True, timeout=10, trust_env=False
        ) as client:
            health = client.get("/api/health")
            assert health.status_code == 200
            assert health.json()["status"] == "healthy"
            assert health.json()["database"] == "ok"
            assert health.json()["schema"] == "vol19.004"
            assert health.json()["bind_host"] == "127.0.0.1"
            page = client.get("/twos")
            assert page.status_code == 200
            assert "First Run" in page.text
            status = client.get("/api/setup/status").json()
            assert status["owner_exists"] is False
            assert status["state"] == "setup_authorization_pending"
            assert client.post(
                "/api/setup/start", json={"confirmation": "START_FIRST_RUN"}
            ).status_code == 200
            assert client.post(
                "/api/setup/start", json={"confirmation": "CONFIRM_INSTALLATION"}
            ).status_code == 200
            owner = client.post(
                "/api/setup/owner",
                json={
                    "username": USERNAME,
                    "password": password,
                    "password_confirmation": password,
                    "setup_authorization": setup_code,
                    "request_id": "real-bootstrap-owner-request-0001",
                },
            )
            assert owner.status_code == 201, owner.text
            assert owner.json()["authenticated"] is True
            assert client.post(
                "/api/setup/workspace",
                json={"path": str(workspace), "create_if_missing": False},
            ).status_code == 200
            assert client.post(
                "/api/setup/optional-tools", json={"decision": "skip"}
            ).status_code == 200
            assert client.post(
                "/api/setup/finish", json={"confirmation": "FINISH_FIRST_RUN"}
            ).json()["state"] == "ready"
            projects = client.get("/api/projects").json()
            assert len(projects) == 1
            created_task = client.post(
                "/api/tasks",
                json={
                    "project_id": projects[0]["id"],
                    "title": "VOL19 19.2A — First Fresh Install Task",
                    "development_task": "Verify bootstrap persistence without external execution.",
                    "objective": "Create and reopen the first task.",
                    "workflow_type": "general",
                    "action": "Analyze",
                },
            )
            assert created_task.status_code == 200
            task_id = created_task.json()["id"]
            assert created_task.json()["status"] == "draft"
            assert client.get("/api/codex/status").json()["passive"] is True

        terminate_owned_process(first_pid)
        first_pid = None
        restarted = subprocess.run(
            command,
            cwd=source,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=180,
            check=False,
        )
        assert restarted.returncode == 0, restarted.stderr
        second_pid = int(
            next(
                line.split(":", 1)[1]
                for line in restarted.stdout.splitlines()
                if line.startswith("Runtime PID:")
            )
        )
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            follow_redirects=True,
            timeout=10,
            trust_env=False,
        ) as client:
            assert client.post(
                "/api/auth/login", json={"username": USERNAME, "password": password}
            ).status_code == 200
            tasks = client.get("/api/tasks").json()
            assert len(tasks) == 1
            assert tasks[0]["id"] == task_id
            assert tasks[0]["title"] == "VOL19 19.2A — First Fresh Install Task"

        with closing(sqlite3.connect(data / "twos.sqlite3")) as connection, connection:
            for table in (
                "task_runs",
                "codex_instruction_packs",
                "codex_runs",
                "ai_model_invocation_evidence",
                "apply_sessions",
                "local_commit_executions",
                "push_executions",
            ):
                assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
        assert source_snapshot(source) == before_source
        runtime_log = next(logs.rglob("runtime.log")).read_text(encoding="utf-8")
        assert password not in runtime_log
        assert setup_code not in runtime_log
        assert "OPENAI_API_KEY" not in runtime_log
    finally:
        if first_pid is not None:
            terminate_owned_process(first_pid)
        if second_pid is not None:
            terminate_owned_process(second_pid)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    time.sleep(0.1)
            except OSError:
                break
        else:
            raise AssertionError("the final isolated runtime did not release its localhost port")
    assert twos_bootstrap.configured_live_pid(data / "runtime.pid") is None
    assert source_snapshot(source) == before_source
