"""Download a file once and keep it in data/cache/."""

from __future__ import annotations

from pathlib import Path

import httpx


def download(url: str, target: Path, refresh: bool = False) -> Path:
    """Fetch `url` to `target`. Re-download only if `refresh` or the file is missing."""
    if refresh or not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        response = httpx.get(url, timeout=60, follow_redirects=True)
        response.raise_for_status()
        target.write_bytes(response.content)
    return target
