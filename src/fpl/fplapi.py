from __future__ import annotations

import gzip
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any  # we'd need to change this, nothing must use Any

import httpx

from fpl.config import Settings

log = logging.getLogger(__name__)


class FplClient:
    def __init__(self, settings: Settings, save_raw: bool = True) -> None:
        """FplClient is the only code to make HTTP requests to the FPL API"""

        self._settings = settings
        self._save_raw = save_raw
        self._http = httpx.Client(
            base_url=settings.fpl_base_url,
            headers={"User-Agent": settings.user_agent},
            timeout=30.0,
            follow_redirects=True,
        )

    def get(self, path: str, retries: int = 3) -> Any:
        """GET one endpoint, e.g. "bootstrap-static/". Retries on network errors and 5xx."""

        for attempt in range(1, retries + 1):
            try:
                response = self._http.get(path)
                if response.status_code < 500:
                    response.raise_for_status()
                    data = response.json()
                    if self._save_raw:
                        self._write_raw(path, data)
                    return data
                log.warning("%s returned %s (attempt %d)",
                            path, response.status_code, attempt)
            except httpx.TransportError as exc:
                log.warning("%s failed: %s (attempt %d)", path, exc, attempt)
            time.sleep(2 ** attempt)

        raise RuntimeError(
            f"FPL API request failed after {retries} attempts: {path}")

    # Named helpers to prevent callers from building URLS by hand
    def bootstrap(self) -> dict:
        return self.get("bootstrap-static/")

    def fixtures(self) -> list[dict]:
        return self.get("fixtures/")

    def live(self, gw: int) -> dict:
        return self.get(f"event/{gw}/live/")

    def element_summary(self, element: int) -> dict:
        return self.get(f"element-summary/{element}/")

    def entry(self, entry_id: int) -> dict:
        return self.get(f"entry/{entry_id}/")

    def entry_history(self, entry_id: int) -> dict:
        return self.get(f"entry/{entry_id}/history/")

    def entry_transfers(self, entry_id: int) -> list[dict]:
        return self.get(f"entry/{entry_id}/transfers/")

    def entry_picks(self, entry_id: int, gw: int) -> dict:
        return self.get(f"entry/{entry_id}/event/{gw}/picks/")

    def _write_raw(self, path: str, data: Any) -> None:
        now = datetime.now(timezone.utc)
        slug = re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")
        folder = self._settings.raw_dir / now.strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)

        target = folder / f"{now.strftime('%H%M%S')}_{slug}.json.gz"
        with gzip.open(target, "wt", encoding="utf-8") as fh:
            json.dump(data, fh)
