from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
STATIC_COCKPIT_DIR = ROOT_DIR / "static_cockpit"
TWOS_UI_PATH = STATIC_COCKPIT_DIR / "vol12_static_mvp" / "twos_command_center.html"


@dataclass(frozen=True)
class Settings:
    database_url: str
    session_ttl_seconds: int = 60 * 60 * 12
    scheduler_poll_seconds: float = 1.0
    static_cockpit_dir: Path = STATIC_COCKPIT_DIR
    ui_path: Path = TWOS_UI_PATH
    source_repo: Path = ROOT_DIR
    worktree_root: Path = Path(tempfile.gettempdir()) / "twos-worktrees"
    codex_spool_root: Path = Path(tempfile.gettempdir()) / "twos-codex-exec-spool"
    codex_executable: str | None = None
    codex_model_identifier: str | None = None
    codex_model_capabilities: tuple[str, ...] = ("coding",)
    codex_timeout_seconds: int = 900
    # Gate Zero on Codex CLI 0.144.4 took ~122 seconds while safely falling
    # back from WebSockets to HTTPS. Keep this explicit and bounded, with
    # enough evidence-based headroom for the same detached path.
    codex_connectivity_timeout_seconds: int = 180
    codex_output_limit: int = 200_000
    # Optional operator-configured, deterministic local Verification backend.
    # This is never populated from Owner/UI input and is invoked as an exact
    # argument vector with the isolated Run worktree as cwd.
    local_verification_command: tuple[str, ...] = ()
    local_verification_timeout_seconds: int = 60
    local_verification_output_limit: int = 20_000
    # The canonical 19.2A launcher sets these fields explicitly.  Their
    # defaults preserve the developer/test runtime that predates First Run.
    fresh_install: bool = False
    installation_id: str | None = None
    data_root: Path | None = None
    runtime_environment: Path | None = None
    log_directory: Path | None = None
    installation_config_path: Path | None = None
    setup_authorization_path: Path | None = None
    bind_host: str = "127.0.0.1"
    bind_port: int | None = None
    session_cookie_name: str = "twos_session"
    maintenance_mode: bool = False


def _environment_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().casefold() in {"1", "true", "yes", "on"}


def _optional_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def _local_verification_command() -> tuple[str, ...]:
    raw = os.environ.get("TWOS_LOCAL_VERIFICATION_COMMAND_JSON", "").strip()
    if not raw:
        return ()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "TWOS_LOCAL_VERIFICATION_COMMAND_JSON must be a JSON argument-vector array."
        ) from exc
    if not isinstance(decoded, list) or not 1 <= len(decoded) <= 32:
        raise ValueError(
            "TWOS_LOCAL_VERIFICATION_COMMAND_JSON must contain 1 to 32 arguments."
        )
    command: list[str] = []
    for value in decoded:
        if (
            not isinstance(value, str)
            or not value
            or "\0" in value
            or len(value.encode("utf-8")) > 4096
        ):
            raise ValueError(
                "TWOS_LOCAL_VERIFICATION_COMMAND_JSON contains an invalid argument."
            )
        command.append(value)
    return tuple(command)


def get_settings() -> Settings:
    db_url = os.environ.get("TWOS_DATABASE_URL")
    if not db_url:
        db_path = os.environ.get("TWOS_DATABASE_PATH", str(ROOT_DIR / "twos_runtime.sqlite3"))
        db_url = f"sqlite:///{db_path}"
    return Settings(
        database_url=db_url,
        source_repo=Path(os.environ.get("TWOS_SOURCE_REPO", str(ROOT_DIR))).expanduser(),
        worktree_root=Path(
            os.environ.get("TWOS_WORKTREE_ROOT", str(Path(tempfile.gettempdir()) / "twos-worktrees"))
        ).expanduser(),
        codex_spool_root=Path(
            os.environ.get(
                "TWOS_CODEX_SPOOL_ROOT",
                str(Path(tempfile.gettempdir()) / "twos-codex-exec-spool"),
            )
        ).expanduser(),
        codex_executable=os.environ.get("TWOS_CODEX_EXECUTABLE"),
        codex_model_identifier=os.environ.get("TWOS_CODEX_MODEL_ID"),
        codex_model_capabilities=tuple(
            item.strip()
            for item in os.environ.get("TWOS_CODEX_MODEL_CAPABILITIES", "coding").split(",")
            if item.strip()
        ),
        codex_timeout_seconds=int(os.environ.get("TWOS_CODEX_TIMEOUT_SECONDS", "900")),
        codex_connectivity_timeout_seconds=int(
            os.environ.get("TWOS_CODEX_CONNECTIVITY_TIMEOUT_SECONDS", "180")
        ),
        codex_output_limit=int(os.environ.get("TWOS_CODEX_OUTPUT_LIMIT", "200000")),
        local_verification_command=_local_verification_command(),
        local_verification_timeout_seconds=int(
            os.environ.get("TWOS_LOCAL_VERIFICATION_TIMEOUT_SECONDS", "60")
        ),
        local_verification_output_limit=int(
            os.environ.get("TWOS_LOCAL_VERIFICATION_OUTPUT_LIMIT", "20000")
        ),
        fresh_install=_environment_flag("TWOS_FRESH_INSTALL"),
        installation_id=os.environ.get("TWOS_INSTALLATION_ID") or None,
        data_root=_optional_path("TWOS_DATA_ROOT"),
        runtime_environment=_optional_path("TWOS_RUNTIME_ENVIRONMENT"),
        log_directory=_optional_path("TWOS_LOG_DIRECTORY"),
        installation_config_path=_optional_path("TWOS_INSTALLATION_CONFIG"),
        setup_authorization_path=_optional_path("TWOS_SETUP_AUTHORIZATION_PATH"),
        bind_host=os.environ.get("TWOS_BIND_HOST", "127.0.0.1"),
        bind_port=(
            int(os.environ["TWOS_BIND_PORT"])
            if os.environ.get("TWOS_BIND_PORT")
            else None
        ),
        session_cookie_name=os.environ.get("TWOS_SESSION_COOKIE_NAME", "twos_session"),
        maintenance_mode=_environment_flag("TWOS_MAINTENANCE_MODE"),
    )
