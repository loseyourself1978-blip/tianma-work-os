from __future__ import annotations

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
    codex_executable: str | None = None
    codex_timeout_seconds: int = 900
    codex_output_limit: int = 200_000


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
        codex_executable=os.environ.get("TWOS_CODEX_EXECUTABLE"),
        codex_timeout_seconds=int(os.environ.get("TWOS_CODEX_TIMEOUT_SECONDS", "900")),
        codex_output_limit=int(os.environ.get("TWOS_CODEX_OUTPUT_LIMIT", "200000")),
    )
