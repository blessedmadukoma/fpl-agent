from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    entry_id: int | None
    data_dir: Path
    user_agent: str = "fpl-agent/0.1 (personal research project)"
    current_season: str = "2026-27"
    history_season: str = "2025-26"
    fpl_base_url: str = ""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "fpl.duckdb"

    @property
    def raw_dir(self) -> Path:
        """Every APi response is saved here, so any result can be reproduced later"""
        return self.data_dir / "raw"

    @property
    def cache_dir(self) -> Path:
        """Downloaded third-party files (historical data, odds)."""
        return self.data_dir / "cache"


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    entry = os.getenv("FPL_ENTRY_ID", "").strip()
    data_dir = Path(os.getenv("FPL_DATA_DIR", PROJECT_ROOT / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)

    current_season = os.getenv("CURRENT_SEASON", "")
    history_season = os.getenv("HISTORY_SEASON", "")
    fpl_base_url = os.getenv("FPL_BASE_URL", "")

    return Settings(
        entry_id=int(entry) if entry else None,
        data_dir=data_dir,
        current_season=current_season,
        history_season=history_season,
        fpl_base_url=fpl_base_url
    )
