from __future__ import annotations

import os
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


def get_settings() -> Settings:
    db_url = os.environ.get("TWOS_DATABASE_URL")
    if not db_url:
        db_path = os.environ.get("TWOS_DATABASE_PATH", str(ROOT_DIR / "twos_runtime.sqlite3"))
        db_url = f"sqlite:///{db_path}"
    return Settings(database_url=db_url)
