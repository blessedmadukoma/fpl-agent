"""Load historical data: last season's results (vaastav) and pre-deadline snapshots (fplcache).

- vaastav/Fantasy-Premier-League: one row per player per fixture, after the fixture.
- Randdalf/fplcache: raw bootstrap-static about four times a day since 2021. We take the
  last snapshot before each deadline: that is what a model could have known at the time.
"""

from __future__ import annotations

import datetime as dt
import json
import lzma
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from fpl.config import Settings
from fpl.ingest.current import LIVE_STATS, events_frame, state_frame, teams_frame
from fpl.ingest.download import download
from fpl.storage import replace_rows

VAASTAV_URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/{season}/{file}"
FPLCACHE_REPO = "https://github.com/Randdalf/fplcache.git"
VAASTAV_POSITIONS = {"GK": "GKP", "GKP": "GKP",
                     "DEF": "DEF", "MID": "MID", "FWD": "FWD"}


@dataclass(frozen=True)
class SeasonWindow:
    """The dates of one FPL season, used to pick fplcache snapshots."""
    season: str
    start: datetime
    end: datetime

    @classmethod
    def for_season(cls, season: str) -> SeasonWindow:
        first_year = int(season[:4])
        return cls(
            season,
            datetime(first_year, 7, 1, tzinfo=dt.UTC),
            datetime(first_year + 1, 6, 30, tzinfo=dt.UTC),
        )


class FplCache:
    """A blob-less git clone: we list every file, then download only the ones we need."""

    def __init__(self, settings: Settings) -> None:
        self.repo = (settings.cache_dir / "fplcache").resolve()

    def sync(self) -> None:
        if not (self.repo / ".git").exists():
            self.repo.parent.mkdir(parents=True, exist_ok=True)
            self._git("clone", "--filter=blob:none", "--no-checkout", FPLCACHE_REPO, str(self.repo),
                      cwd=self.repo.parent)
        else:
            self._git("fetch", "--filter=blob:none", "origin")
            self._git("reset", "--soft", "origin/HEAD")

    def index(self) -> pd.DataFrame:
        """Every snapshot path with its UTC timestamp (taken from the path)."""
        names = self._git("ls-tree", "-r", "--name-only",
                          "HEAD", "cache").split()
        rows = []
        for name in names:
            parts = name.removesuffix(".json.xz").split(
                "/")  # cache/Y/M/D/HHMM
            if len(parts) != 5:
                continue
            _, y, m, d, hm = parts
            time = datetime(int(y), int(m), int(d), int(
                hm[:2]), int(hm[2:]), tzinfo=dt.UTC)
            rows.append({"path": name, "time": time})
        return pd.DataFrame(rows).sort_values("time", ignore_index=True)

    def read(self, paths: list[str]) -> dict[str, dict]:
        """Download (if needed) and parse snapshots."""
        missing = [p for p in paths if not (self.repo / p).exists()]
        if missing:
            self._git("checkout", "HEAD", "--", *missing)
        return {p: json.loads(lzma.open(self.repo / p).read()) for p in paths}

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd or self.repo, capture_output=True, text=True, check=True)
        return result.stdout


def load_states_from_fplcache(settings: Settings, con, season: str, with_metadata: bool = True) -> dict:
    """Write one pre-deadline `state` snapshot per past GW.

    With `with_metadata`, also write that season's events, teams and scoring rules. Use it for
    past seasons only: for the current season, `fpl update` writes fresher versions.
    """
    cache = FplCache(settings)
    cache.sync()
    index = cache.index()
    window = SeasonWindow.for_season(season)
    in_season = index[(index.time >= window.start)
                      & (index.time <= window.end)]

    latest_path = in_season.path.iloc[-1]
    latest = cache.read([latest_path])[latest_path]
    events = events_frame(latest, season)
    past = events[events.deadline < datetime.now(dt.UTC)]

    chosen = {}
    for gw, deadline in zip(past.gw, past.deadline):
        before = in_season[in_season.time < deadline]
        if not before.empty:
            chosen[int(gw)] = before.iloc[-1]
    snapshots = cache.read([row.path for row in chosen.values()])

    for gw, row in chosen.items():
        state = state_frame(snapshots[row.path],
                            season, gw, snapshot_time=row.time)
        replace_rows(con, "state", state, season=season, gw=gw)

    if with_metadata:
        replace_rows(con, "events", events, season=season)
        replace_rows(con, "teams", teams_frame(latest, season), season=season)
        rules = pd.DataFrame(
            [{"season": season, "game_config": json.dumps(latest["game_config"])}])
        replace_rows(con, "rules", rules, season=season)

    lead_hours = [(past.set_index("gw").deadline[gw] -
                   row.time).total_seconds() / 3600 for gw, row in chosen.items()]
    return {"season": season, "gws": len(chosen), "median_lead_h": pd.Series(lead_hours).median(),
            "max_lead_h": max(lead_hours)}


def load_vaastav_season(settings: Settings, con, season: str) -> dict:
    """Write `player_fixture`, `player_gw` and `fixtures` for a finished season.

    Needs the `teams` rows for that season (written by load_states_from_fplcache).
    """
    folder = settings.cache_dir / "vaastav" / season
    merged = pd.read_csv(download(VAASTAV_URL.format(
        season=season, file="gws/merged_gw.csv"), folder / "merged_gw.csv"))
    fixtures_raw = pd.read_csv(download(VAASTAV_URL.format(
        season=season, file="fixtures.csv"), folder / "fixtures.csv"))

    teams = con.execute(
        "select team_id, name from teams where season = ?", [season]).df()
    team_ids = dict(zip(teams.name, teams.team_id))

    player_fixture = pd.DataFrame(
        {
            "season": season,
            "gw": merged["round"].astype(int),
            "fixture": merged["fixture"].astype(int),
            "element": merged["element"].astype(int),
            "position": merged["position"].map(VAASTAV_POSITIONS),
            "team": merged["team"].map(team_ids),
            **{stat: merged[stat].astype(float) for stat in LIVE_STATS},
        }
    )
    if player_fixture[["position", "team"]].isna().any().any():
        raise ValueError(
            "Unmapped position or team name in vaastav data; check VAASTAV_POSITIONS and teams.")

    player_gw = (
        player_fixture.groupby(
            ["season", "gw", "element", "position", "team"], as_index=False)
        .agg(**{stat: (stat, "sum") for stat in LIVE_STATS}, n_fixtures=("fixture", "count"))
    )
    fixtures = pd.DataFrame(
        {
            "season": season,
            "fixture_id": fixtures_raw["id"],
            "gw": fixtures_raw["event"],
            "kickoff": pd.to_datetime(fixtures_raw["kickoff_time"], utc=True),
            "team_h": fixtures_raw["team_h"],
            "team_a": fixtures_raw["team_a"],
            "goals_h": fixtures_raw["team_h_score"],
            "goals_a": fixtures_raw["team_a_score"],
            "finished": fixtures_raw["finished"].astype(bool),
        }
    )
    replace_rows(con, "player_fixture", player_fixture, season=season)
    replace_rows(con, "player_gw", player_gw, season=season)
    replace_rows(con, "fixtures", fixtures, season=season)
    return {"season": season, "player_fixture_rows": len(player_fixture), "player_gw_rows": len(player_gw),
            "fixtures": len(fixtures)}
