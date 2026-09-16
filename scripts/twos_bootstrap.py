#!/usr/bin/env python3
"""Canonical source-distribution bootstrap for TWOS 19.2A.

This file intentionally uses only the Python standard library and Python 3.9
syntax so the system interpreter can diagnose and locate a supported runtime
without installing anything globally.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SUPPORTED_PYTHON_MIN = (3, 11)
SUPPORTED_PYTHON_MAX = (3, 14)
APP_VERSION = "0.17.0"
LATEST_SCHEMA = "vol19.005"
DEFAULT_HEALTH_TIMEOUT = 60.0
INSTALLATION_ID_RE = re.compile(r"^install_[a-f0-9]{32}$")
SENSITIVE_CHILD_PREFIXES = (
    "CODEX_",
    "CLAUDE_",
    "OPENAI_",
    "ANTHROPIC_",
    "GEMINI_",
    "DEEPSEEK_",
    "QIANWEN_",
    "GITHUB_",
    "GITLAB_",
    "BITBUCKET_",
    "AWS_",
    "AZURE_",
    "GOOGLE_",
    "SMTP_",
    "MAIL_",
    "CALENDAR_",
    "SLACK_",
    "NOTION_",
    "DROPBOX_",
    "STRIPE_",
)
PYTHON_INJECTION_VARIABLES = frozenset(
    {"PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONINSPECT", "VIRTUAL_ENV", "NODE_OPTIONS", "NODE_PATH"}
)
SENSITIVE_CHILD_NAMES = frozenset({"GH_TOKEN", "GH_ENTERPRISE_TOKEN"})


class BootstrapError(RuntimeError):
    pass


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise BootstrapError("A required installation directory is unsafe.")
    os.chmod(path, 0o700)


def atomic_private_json(path: Path, payload: Dict[str, Any]) -> None:
    private_directory(path.parent)
    temporary = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        content = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        os.write(descriptor, content)
        os.fsync(descriptor)
        os.replace(temporary, path)
    finally:
        os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def read_json(path: Path) -> Dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise BootstrapError("The existing installation configuration is unsafe.") from exc
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1) or metadata.st_mode & 0o077:
        raise BootstrapError("The existing installation configuration is unsafe.")
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1) or opened.st_mode & 0o077:
            raise BootstrapError("The existing installation configuration is unsafe.")
        encoded = os.read(descriptor, 65_537)
        if len(encoded) > 65_536:
            raise BootstrapError("The existing installation configuration is invalid.")
        value = json.loads(encoded.decode("utf-8"))
    except BootstrapError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BootstrapError("The existing installation configuration is invalid.") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise BootstrapError("The existing installation configuration is invalid.")
    return value


def path_contains(parent: Path, child: Path) -> bool:
    return parent == child or parent in child.parents


def reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink():
            raise BootstrapError("An installation path contains a symbolic-link boundary.")


def validate_source_root(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts:
        raise BootstrapError("The TWOS source root must be an absolute normalized path.")
    reject_symlink_components(path)
    resolved = path.resolve(strict=True)
    required = (
        resolved / "requirements.txt",
        resolved / "twos_runtime" / "app.py",
        resolved / "static_cockpit" / "vol12_static_mvp" / "twos_command_center.html",
    )
    if not all(item.is_file() for item in required):
        raise BootstrapError("This directory is not a complete TWOS source distribution.")
    return resolved


def validate_installation_path(path: Path, source_root: Path, label: str) -> Path:
    if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
        raise BootstrapError("%s must be an absolute path without traversal." % label)
    reject_symlink_components(path)
    resolved = path.resolve(strict=False)
    source = source_root.resolve(strict=True)
    if (
        path_contains(source, resolved)
        or path_contains(resolved, source)
        or ".git" in resolved.parts
    ):
        raise BootstrapError("%s must remain outside the TWOS source repository." % label)
    if resolved == Path.home().resolve(strict=True):
        raise BootstrapError("%s cannot authorize the entire home directory." % label)
    return resolved


def bootstrap_environment(*, package_install: bool = False) -> Dict[str, str]:
    names = {"PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE",
             "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy",
             "https_proxy", "all_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR",
             "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "NODE_EXTRA_CA_CERTS"}
    if package_install:
        names.update({"PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_TRUSTED_HOST",
            "PIP_CERT", "PIP_CLIENT_CERT", "PIP_CONFIG_FILE", "PIP_NO_INDEX",
            "PIP_FIND_LINKS", "PIP_CACHE_DIR", "PIP_DISABLE_PIP_VERSION_CHECK"})
    return {key: value for key, value in os.environ.items() if key in names}


def python_version(executable: str) -> Optional[Tuple[int, int, int]]:
    try:
        completed = subprocess.run(
            [
                executable,
                "-c",
                "import sys; print('.'.join(str(v) for v in sys.version_info[:3]))",
            ],
            env=bootstrap_environment(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        parts = tuple(int(item) for item in completed.stdout.strip().split("."))
    except ValueError:
        return None
    return parts if len(parts) == 3 else None


def supported_python(version: Tuple[int, int, int]) -> bool:
    return SUPPORTED_PYTHON_MIN <= version[:2] < SUPPORTED_PYTHON_MAX


def select_python(explicit: Optional[str] = None) -> Tuple[str, Tuple[int, int, int]]:
    if explicit:
        resolved_explicit = (
            shutil.which(explicit)
            if os.sep not in explicit and (os.altsep is None or os.altsep not in explicit)
            else explicit
        )
        candidates = [resolved_explicit or explicit]
    else:
        candidates = [sys.executable]
        for name in ("python3.13", "python3.12", "python3.11", "python3"):
            candidate = shutil.which(name)
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    observed: List[str] = []
    for candidate in candidates:
        version = python_version(candidate)
        if version is None:
            observed.append("%s unavailable" % Path(candidate).name)
            continue
        observed.append("%s %s" % (Path(candidate).name, ".".join(map(str, version))))
        if supported_python(version):
            return str(Path(candidate).resolve()), version
    raise BootstrapError(
        "TWOS requires Python 3.11, 3.12, or 3.13. Detected: %s. Install a supported Python and run ./start-twos again."
        % (", ".join(observed) or "none")
    )


def dependency_digest(source_root: Path, version: Tuple[int, int, int]) -> str:
    digest = hashlib.sha256()
    manifest = source_root / "requirements.txt"
    digest.update(manifest.read_bytes())
    digest.update(("python=%d.%d" % version[:2]).encode("ascii"))
    return digest.hexdigest()


def append_log(path: Path, message: str) -> None:
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_APPEND
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            0o600,
        )
    except OSError as exc:
        raise BootstrapError("The private runtime log path is unsafe.") from exc
    try:
        if not safe_control_file(os.fstat(descriptor)):
            raise BootstrapError("The private runtime log is not a regular file.")
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, ("%s %s\n" % (timestamp, message)).encode("utf-8"))
    finally:
        os.close(descriptor)


def ensure_runtime_environment(
    source_root: Path,
    runtime_root: Path,
    python_executable: str,
    version: Tuple[int, int, int],
    log_path: Path,
    refresh: bool,
) -> Path:
    environment = runtime_root / "venv"
    marker = runtime_root / "dependency-state.json"
    expected_digest = dependency_digest(source_root, version)
    if environment.is_symlink():
        raise BootstrapError("The isolated runtime environment path is unsafe.")
    if environment.exists() and marker.exists():
        state = read_json(marker)
        if state.get("dependency_digest") == expected_digest:
            runtime_python = environment / "bin" / "python"
            if (
                runtime_python.is_file()
                and supported_python(python_version(str(runtime_python)) or (0, 0, 0))
                and runtime_environment_fingerprint(runtime_python)
                == state.get("installed_fingerprint")
            ):
                return runtime_python
            if not refresh:
                raise BootstrapError(
                    "The isolated runtime environment failed its integrity check. Re-run ./start-twos --refresh-dependencies."
                )
        if not refresh:
            raise BootstrapError(
                "Dependency metadata changed. Re-run ./start-twos --refresh-dependencies to perform the controlled refresh."
            )
    elif environment.exists() and not refresh:
        raise BootstrapError(
            "The isolated runtime environment is incomplete. Re-run ./start-twos --refresh-dependencies."
        )
    if refresh and environment.exists():
        # A controlled refresh keeps the directory identity but rebuilds the
        # environment through venv --clear; it never touches global packages.
        clear_flag = "--clear"
    else:
        clear_flag = None
    private_directory(runtime_root)
    command = [python_executable, "-m", "venv"]
    if clear_flag:
        command.append(clear_flag)
    command.append(str(environment))
    append_log(log_path, "Creating isolated Python runtime environment.")
    created = subprocess.run(
        command,
        env=bootstrap_environment(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=180,
        check=False,
    )
    if created.returncode != 0:
        raise BootstrapError("The isolated Python runtime environment could not be created. See the private runtime log.")
    runtime_python = environment / "bin" / "python"
    append_log(log_path, "Installing dependencies from requirements.txt into the isolated runtime environment.")
    installed = subprocess.run(
        [
            str(runtime_python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--require-virtualenv",
            "-r",
            str(source_root / "requirements.txt"),
        ],
        cwd=str(source_root),
        env=bootstrap_environment(package_install=True),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=900,
        check=False,
    )
    # Package-manager configuration can contain private index details even
    # when requirements.txt does not.  Persist only a stable exit summary,
    # never raw package-manager output.
    append_log(log_path, "Dependency installation exited with status %d." % installed.returncode)
    if installed.returncode != 0:
        raise BootstrapError(
            "TWOS dependencies could not be installed. Network download access may be required; see the private runtime log and retry explicitly."
        )
    installed_fingerprint = runtime_environment_fingerprint(runtime_python)
    if not installed_fingerprint:
        raise BootstrapError(
            "The isolated runtime environment did not pass its dependency integrity check. Re-run with --refresh-dependencies."
        )
    atomic_private_json(
        marker,
        {
            "dependency_digest": expected_digest,
            "installed_fingerprint": installed_fingerprint,
            "manifest": "requirements.txt",
            "python": "%d.%d.%d" % version,
        },
    )
    return runtime_python


def runtime_environment_fingerprint(runtime_python: Path) -> Optional[str]:
    checks = (
        [str(runtime_python), "-m", "pip", "check"],
        [
            str(runtime_python),
            "-c",
            "import fastapi,httpx,pydantic,sqlalchemy,uvicorn; print('twos-runtime-ok')",
        ],
        [str(runtime_python), "-m", "pip", "freeze", "--all"],
    )
    outputs: List[str] = []
    for command in checks:
        try:
            completed = subprocess.run(
                command,
                env=bootstrap_environment(package_install=True),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        outputs.append(completed.stdout.strip())
    return hashlib.sha256("\0".join(outputs).encode("utf-8")).hexdigest()


def available_port(requested: Optional[int]) -> int:
    if requested is not None and not 1 <= requested <= 65535:
        raise BootstrapError("The requested localhost port is invalid.")
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Permit a truthful restart after prior localhost HTTP connections
        # leave short-lived TIME_WAIT sockets. A live listener still blocks
        # the final exclusive listen admission below.
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", requested or 0))
        except OSError as exc:
            raise BootstrapError(
                "The requested localhost port is unavailable; no fallback port was selected."
            ) from exc
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def reserve_port(port: int) -> socket.socket:
    reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    reservation.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        reservation.bind(("127.0.0.1", port))
        reservation.listen(2048)
        reservation.set_inheritable(True)
        return reservation
    except OSError as exc:
        reservation.close()
        raise BootstrapError(
            "The persisted localhost port became unavailable before startup; no fallback was used."
        ) from exc


def pid_is_live(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def acquire_startup_lock(path: Path) -> int:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        metadata = None
    if metadata is not None and (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1):
        raise BootstrapError("The startup-lock path is unsafe.")
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(
            path,
            os.O_WRONLY
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
            0o600,
        )
        if not safe_control_file(os.fstat(descriptor)):
            os.close(descriptor)
            descriptor = None
            raise BootstrapError("The startup-lock path is unsafe.")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return descriptor
    except BlockingIOError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise BootstrapError("Another TWOS startup is already in progress for this data root.") from exc
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise BootstrapError("The startup-lock path is unsafe.") from exc


def safe_control_file(metadata) -> bool:
    return stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1


def write_pid(path: Path, pid: int) -> None:
    try:
        existing = path.lstat()
    except FileNotFoundError:
        existing = None
    if existing is not None and not safe_control_file(existing):
        raise BootstrapError("The runtime PID path is unsafe.")
    temporary = path.with_name(".%s.%s.tmp" % (path.name, uuid.uuid4().hex))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, (str(pid) + "\n").encode("ascii"))
        os.fsync(descriptor)
        os.replace(temporary, path)
    finally:
        os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def read_pid(path: Path) -> int:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        raise
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1):
        raise BootstrapError("The runtime PID file is unsafe.")
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        if not safe_control_file(os.fstat(descriptor)):
            raise BootstrapError("The runtime PID file is unsafe.")
        raw = os.read(descriptor, 65)
        decoded = raw.decode("ascii")
        if not re.fullmatch(r"[1-9][0-9]{0,18}\n?", decoded):
            raise BootstrapError("The runtime PID file is invalid.")
        pid = int(decoded.strip())
        if pid > 2_147_483_647:
            raise BootstrapError("The runtime PID file is invalid.")
    except BootstrapError:
        raise
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise BootstrapError("The runtime PID file is invalid.") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return pid


def configured_live_pid(path: Path) -> Optional[int]:
    try:
        pid = read_pid(path)
    except FileNotFoundError:
        return None
    return pid if pid_is_live(pid) else None


def child_environment(
    source_root: Path,
    data_root: Path,
    runtime_root: Path,
    log_root: Path,
    installation: Dict[str, Any],
) -> Dict[str, str]:
    environment = bootstrap_environment()
    if "SSH_AUTH_SOCK" in os.environ:
        environment["SSH_AUTH_SOCK"] = os.environ["SSH_AUTH_SOCK"]
    installation_id = str(installation["installation_id"])
    environment.update(
        {
            "PYTHONUNBUFFERED": "1",
            # A source distribution is immutable at runtime, including ignored
            # bytecode cache files.
            "PYTHONDONTWRITEBYTECODE": "1",
            "TWOS_FRESH_INSTALL": "1",
            "TWOS_INSTALLATION_ID": installation_id,
            "TWOS_DATA_ROOT": str(data_root),
            "TWOS_DATABASE_PATH": str(data_root / "twos.sqlite3"),
            "TWOS_RUNTIME_ENVIRONMENT": str(runtime_root / "venv"),
            "TWOS_LOG_DIRECTORY": str(log_root),
            "TWOS_INSTALLATION_CONFIG": str(data_root / "installation.json"),
            "TWOS_SETUP_AUTHORIZATION_PATH": str(data_root / "setup-authorization.txt"),
            "TWOS_BIND_HOST": "127.0.0.1",
            "TWOS_BIND_PORT": str(installation["port"]),
            "TWOS_SESSION_COOKIE_NAME": "twos_session_%s" % installation_id,
            "TWOS_SOURCE_REPO": str(source_root),
            "TWOS_WORKTREE_ROOT": str(runtime_root / "worktrees"),
            "TWOS_CODEX_SPOOL_ROOT": str(runtime_root / "codex-spool"),
        }
    )
    return environment


def health_payload(url: str, timeout: float = 2.0) -> Optional[Dict[str, Any]]:
    try:
        # A localhost readiness check must not inherit a configured network
        # proxy or send installation identity evidence outside loopback.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=timeout) as response:
            if response.status != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def read_setup_authorization(path: Path) -> str:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise BootstrapError("The one-time setup authorization is unavailable.") from exc
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1) or metadata.st_mode & 0o077:
        raise BootstrapError("The one-time setup authorization file is unsafe.")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
    except OSError as exc:
        raise BootstrapError("The one-time setup authorization file is unsafe.") from exc
    try:
        opened = os.fstat(descriptor)
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1) or opened.st_mode & 0o077:
            raise BootstrapError("The one-time setup authorization file is unsafe.")
        try:
            value = os.read(descriptor, 1024).decode("utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise BootstrapError("The one-time setup authorization is invalid.") from exc
    finally:
        os.close(descriptor)
    if not value or len(value) > 256:
        raise BootstrapError("The one-time setup authorization is invalid.")
    return value


def wait_for_health(
    process: subprocess.Popen,
    url: str,
    timeout: float,
    installation_id: str,
) -> Dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise BootstrapError(
                "TWOS exited during startup with status %s. See the private runtime log." % return_code
            )
        payload = health_payload(url)
        if (
            payload
            and payload.get("status") == "healthy"
            and payload.get("database") == "ok"
            and payload.get("version") == APP_VERSION
            and payload.get("schema") == LATEST_SCHEMA
            and payload.get("bind_host") == "127.0.0.1"
            and payload.get("installation_id") == installation_id
        ):
            return payload
        time.sleep(0.2)
    raise BootstrapError("TWOS did not reach a truthful healthy state before the startup deadline.")


def terminate_owned_process(process: subprocess.Popen, *, grace_seconds: float = 10.0) -> None:
    """Bounded cleanup for the one child started by this launcher."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        # The child exited between poll() and terminate(). There is no longer
        # an owned process to signal; a nonblocking wait reaps it when possible.
        try:
            process.wait(timeout=0)
        except (ChildProcessError, subprocess.TimeoutExpired):
            pass
        return
    try:
        process.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except ChildProcessError:
            pass


def clear_owned_pid(path: Path, pid: int) -> None:
    """Remove only a regular PID file that still names our exact child."""
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1):
        return
    try:
        persisted = read_pid(path)
    except (BootstrapError, FileNotFoundError, OSError, ValueError):
        return
    if persisted == pid:
        path.unlink()


def initial_installation(
    data_root: Path,
    runtime_root: Path,
    log_root: Path,
    requested_port: Optional[int],
) -> Tuple[Dict[str, Any], bool]:
    config_path = data_root / "installation.json"
    entries = (
        [
            entry
            for entry in data_root.iterdir()
            if entry.name not in {"startup.lock", "runtime.pid"}
        ]
        if data_root.exists()
        else []
    )
    if config_path.exists():
        config = read_json(config_path)
        installation_id = str(config.get("installation_id") or "")
        if not INSTALLATION_ID_RE.fullmatch(installation_id):
            raise BootstrapError("The existing installation identity is invalid.")
        expected = {
            "data_root": str(data_root),
            "database_path": str(data_root / "twos.sqlite3"),
            "runtime_environment": str(runtime_root / "venv"),
            "log_directory": str(log_root),
            "bind_host": "127.0.0.1",
            "source_version": APP_VERSION,
        }
        if any(config.get(key) != value for key, value in expected.items()):
            raise BootstrapError("The existing installation configuration does not match this launch.")
        configured_port = config.get("port")
        if type(configured_port) is not int:
            raise BootstrapError("The persisted localhost port is invalid.")
        if requested_port is not None and requested_port != configured_port:
            raise BootstrapError("The requested port differs from the persisted installation port.")
        config["port"] = available_port(configured_port)
        return config, False
    if entries:
        raise BootstrapError(
            "The selected data root is not empty and has no compatible TWOS installation configuration. Nothing was overwritten."
        )
    port = available_port(requested_port)
    config = {
        "installation_id": "install_%s" % uuid.uuid4().hex,
        "source_version": APP_VERSION,
        "data_root": str(data_root),
        "database_path": str(data_root / "twos.sqlite3"),
        "runtime_environment": str(runtime_root / "venv"),
        "log_directory": str(log_root),
        "bind_host": "127.0.0.1",
        "port": port,
        "first_run_state": "uninitialized",
        "setup_completed_at": None,
    }
    return config, True


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="./start-twos")
    value.add_argument("--source-root", help=argparse.SUPPRESS)
    value.add_argument("--data-root")
    value.add_argument("--runtime-root")
    value.add_argument("--log-root")
    value.add_argument("--port", type=int)
    value.add_argument("--python")
    value.add_argument("--refresh-dependencies", action="store_true")
    value.add_argument("--no-browser", action="store_true")
    value.add_argument("--detach", action="store_true")
    value.add_argument("--check", action="store_true")
    value.add_argument("--health-timeout", type=float, default=DEFAULT_HEALTH_TIMEOUT)
    return value


def prepare_data_root(path: Path) -> None:
    """Create a private root, or validate an existing root without changing it."""
    if not path.exists():
        path.mkdir(mode=0o700, parents=True)
        return
    if path.is_symlink() or not path.is_dir():
        raise BootstrapError("The TWOS data root is not a safe directory.")
    if not os.access(path, os.W_OK | os.X_OK):
        raise BootstrapError("The TWOS data root is not writable.")
    if path.stat().st_mode & 0o077:
        raise BootstrapError(
            "The existing TWOS data root is not private to the current user. Choose a user-only directory."
        )


def validate_data_root_contents(path: Path) -> None:
    entries = [entry for entry in path.iterdir() if entry.name not in {"startup.lock", "runtime.pid"}]
    if entries and not (path / "installation.json").is_file():
        raise BootstrapError(
            "The selected data root is not empty and has no compatible TWOS installation configuration. Nothing was overwritten."
        )


def _main(argv: Optional[List[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("BLOCKED: TWOS must not be started as root or with sudo.", file=sys.stderr)
        return 2
    try:
        source_root = validate_source_root(
            Path(arguments.source_root or Path(__file__).resolve().parents[1])
        )
        python_executable, version = select_python(arguments.python)
        home = Path.home().resolve(strict=True)
        data_root = validate_installation_path(
            Path(arguments.data_root).expanduser()
            if arguments.data_root
            else home / "Library" / "Application Support" / "Tianma Work OS",
            source_root,
            "The TWOS data root",
        )
        runtime_base = validate_installation_path(
            Path(arguments.runtime_root).expanduser()
            if arguments.runtime_root
            else home / "Library" / "Caches" / "Tianma Work OS",
            source_root,
            "The TWOS runtime root",
        )
        log_base = validate_installation_path(
            Path(arguments.log_root).expanduser()
            if arguments.log_root
            else home / "Library" / "Logs" / "Tianma Work OS",
            source_root,
            "The TWOS log root",
        )
        roots = (data_root, runtime_base, log_base)
        if any(
            left == right or path_contains(left, right) or path_contains(right, left)
            for index, left in enumerate(roots)
            for right in roots[index + 1 :]
        ):
            raise BootstrapError(
                "The data, runtime, and log roots must be separate directories."
            )
        if arguments.check:
            print("TWOS bootstrap static prerequisites: PASSED")
            print("Source: %s" % source_root)
            print("Python: %s (%s)" % (python_executable, ".".join(map(str, version))))
            print("Data root: %s" % data_root)
            print("Binding: 127.0.0.1 only")
            print("Runtime, data contents, dependencies, port, and health were not started or claimed ready.")
            return 0
        prepare_data_root(data_root)
        validate_data_root_contents(data_root)
        # Read an existing ID before selecting its installation-scoped runtime
        # and log directories.  New IDs are generated only for an empty root.
        existing_config = data_root / "installation.json"
        existing_id = None
        if existing_config.exists():
            existing_id = str(read_json(existing_config).get("installation_id") or "")
            if not INSTALLATION_ID_RE.fullmatch(existing_id):
                raise BootstrapError("The existing installation identity is invalid.")
        installation_id = existing_id or "install_%s" % uuid.uuid4().hex
        runtime_root = runtime_base / installation_id
        log_root = log_base / installation_id
        startup_lock = data_root / "startup.lock"
        lock_descriptor = acquire_startup_lock(startup_lock)
        reservation: Optional[socket.socket] = None
        try:
            pid_path = data_root / "runtime.pid"
            live_pid = configured_live_pid(pid_path)
            if live_pid is not None:
                raise BootstrapError(
                    "TWOS is already running for this data root (PID %d)." % live_pid
                )
            if pid_path.exists():
                pid_path.unlink()
            config, created = initial_installation(
                data_root, runtime_root, log_root, arguments.port
            )
            # initial_installation generated an ID before it knew the scoped
            # roots.  Replace it with the already selected installation ID.
            config["installation_id"] = installation_id
            # Hold the exact loopback listener before persisting a new port or
            # spending time creating dependencies. Uvicorn inherits this same
            # descriptor, so no claimant can steal the published endpoint.
            reservation = reserve_port(int(config["port"]))
            if created:
                config["runtime_environment"] = str(runtime_root / "venv")
                config["log_directory"] = str(log_root)
                atomic_private_json(data_root / "installation.json", config)
            private_directory(runtime_root)
            private_directory(log_root)
            log_path = log_root / "runtime.log"
            runtime_python = ensure_runtime_environment(
                source_root,
                runtime_root,
                python_executable,
                version,
                log_path,
                arguments.refresh_dependencies,
            )
            private_directory(runtime_root / "worktrees")
            private_directory(runtime_root / "codex-spool")
            environment = child_environment(
                source_root, data_root, runtime_root, log_root, config
            )
            url = "http://127.0.0.1:%d/twos" % config["port"]
            health_url = "http://127.0.0.1:%d/api/health" % config["port"]
            output_descriptor = os.open(
                log_path,
                os.O_WRONLY
                | os.O_APPEND
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_NONBLOCK", 0),
            )
            if not safe_control_file(os.fstat(output_descriptor)):
                os.close(output_descriptor)
                reservation.close()
                raise BootstrapError("The private runtime log is not a regular file.")
            output = os.fdopen(output_descriptor, "ab", buffering=0)
            try:
                try:
                    assert reservation is not None
                    process = subprocess.Popen(
                        [
                            str(runtime_python),
                            "-m",
                            "uvicorn",
                            "twos_runtime.app:create_app",
                            "--factory",
                            "--fd",
                            str(reservation.fileno()),
                        ],
                        cwd=str(source_root),
                        env=environment,
                        stdin=subprocess.DEVNULL,
                        stdout=output,
                        stderr=subprocess.STDOUT,
                        start_new_session=arguments.detach,
                        pass_fds=(reservation.fileno(),),
                    )
                finally:
                    reservation.close()
                    reservation = None
            finally:
                output.close()
            previous_handlers: Dict[int, Any] = {}
            forwarded: Dict[str, Any] = {"signal": None, "at": None}

            def forward_signal(signum: int, _frame: Any) -> None:
                if forwarded["signal"] is None:
                    forwarded["signal"] = signum
                    forwarded["at"] = time.monotonic()
                    if process.poll() is None:
                        process.send_signal(
                            signal.SIGINT if signum == signal.SIGINT else signal.SIGTERM
                        )

            # Own the child immediately after Popen. Any signal or failure
            # before a successful detached handoff is forwarded and reaped.
            for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, forward_signal)
            try:
                write_pid(pid_path, process.pid)
                health = wait_for_health(
                    process,
                    health_url,
                    arguments.health_timeout,
                    installation_id,
                )
                append_log(log_path, "Runtime health gate passed on 127.0.0.1.")
                if not arguments.no_browser:
                    try:
                        browser_opened = bool(webbrowser.open(url, new=2))
                    except Exception:
                        browser_opened = False
                    if not browser_opened:
                        append_log(
                            log_path,
                            "Browser opening was unavailable; the published localhost URL remains ready.",
                        )
                print("TWOS is ready: %s" % url)
                print("Runtime PID: %d" % process.pid)
                print("Data root: %s" % data_root)
                print("Runtime environment: %s" % (runtime_root / "venv"))
                print("Private runtime log: %s" % log_path)
                setup_path = data_root / "setup-authorization.txt"
                if setup_path.exists():
                    print("Setup authorization code: %s" % read_setup_authorization(setup_path))
                    print("Setup authorization file: %s" % setup_path)
                else:
                    print("Setup authorization: already consumed; use normal Owner login.")
                print(
                    "Health: %s / database %s"
                    % (health.get("status"), health.get("database"))
                )
            except BaseException:
                terminate_owned_process(process)
                clear_owned_pid(pid_path, process.pid)
                for signum, handler in previous_handlers.items():
                    signal.signal(signum, handler)
                previous_handlers.clear()
                raise
        finally:
            if reservation is not None:
                reservation.close()
            os.close(lock_descriptor)
        if arguments.detach:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
            return 0
        try:
            while True:
                try:
                    return int(process.wait(timeout=0.5))
                except subprocess.TimeoutExpired:
                    if (
                        forwarded["at"] is not None
                        and time.monotonic() - float(forwarded["at"]) > 15
                    ):
                        process.terminate()
                        try:
                            return int(process.wait(timeout=5))
                        except subprocess.TimeoutExpired:
                            process.kill()
                            return int(process.wait(timeout=5))
        finally:
            for signum, handler in previous_handlers.items():
                signal.signal(signum, handler)
            clear_owned_pid(pid_path, process.pid)
    except BootstrapError as exc:
        print("BLOCKED: %s" % exc, file=sys.stderr)
        return 2
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            "BLOCKED: TWOS bootstrap failed safely (%s). No global package installation was attempted."
            % type(exc).__name__,
            file=sys.stderr,
        )
        return 2


def main(argv: Optional[List[str]] = None) -> int:
    # Keep installation files and the launched child private, but do not leak
    # process-global permissions to an embedding caller after any return/error.
    previous_umask = os.umask(0o077)
    try:
        return _main(argv)
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
