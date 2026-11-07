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
    # Removed from the evaluation exports, which are public.
    team_name: str = ""
    league_name: str = ""

    ollama_api_key: str = ""
    ollama_model: str = "gpt-oss:120b"
    ollama_base_url: str = "http://localhost:11434/v1/"
    temperature: float = 0.0

    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = ""
    langfuse_tracing_enabled: bool = True

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
    team_name = os.getenv("FPL_TEAM_NAME", "")
    league_name = os.getenv("FPL_LEAGUE_NAME", "")

    ollama_api_key = os.getenv("OLLAMA_API_KEY", "")
    ollama_model = os.getenv("OLLAMA_MODEL", "")
    ollama_base_url = os.getenv("OLLAMA_BASE_URL", "")
    temperature = os.getenv("TEMPERATURE", "").strip()

    langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    langfuse_base_url = os.getenv("LANGFUSE_BASE_URL", "")
    _raw_tracing = os.getenv(
        "LANGFUSE_TRACING_ENABLED", "true").strip().lower()
    if _raw_tracing in ("1", "true", "yes", "on"):
        langfuse_tracing_enabled = True
    elif _raw_tracing in ("0", "false", "no", "off"):
        langfuse_tracing_enabled = False
    else:
        raise ValueError(
            "Invalid LANGFUSE_TRACING_ENABLED value. "
            "Expected one of: '1', 'true', 'yes', 'on', '0', 'false', 'no', 'off'."
        )

    return Settings(
        entry_id=int(entry) if entry else None,
        data_dir=data_dir,
        current_season=current_season,
        history_season=history_season,
        fpl_base_url=fpl_base_url,
        team_name=team_name,
        league_name=league_name,
        ollama_base_url=ollama_base_url,
        ollama_api_key=ollama_api_key,
        ollama_model=ollama_model,
        temperature=float(temperature) if temperature else 0.0,
        langfuse_base_url=langfuse_base_url,
        langfuse_public_key=langfuse_public_key,
        langfuse_secret_key=langfuse_secret_key,
        langfuse_tracing_enabled=langfuse_tracing_enabled
    )
