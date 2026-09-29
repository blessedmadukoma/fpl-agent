"""Bookmaker odds from football-data.co.uk, turned into expected goals per team per fixture.

- mmz4281/{yyyy}/E0.csv: every Premier League match of a season, with pre-match odds.
- fixtures.csv: the coming round's matches. Weekend odds appear on Friday afternoon.
We use the market average (Avg*) columns. See 01-reference.md H.4.
"""

from __future__ import annotations

import pandas as pd

from fpl.config import Settings
from fpl.ingest.download import download
from fpl.projections.goals import rates_from_odds
from fpl.storage import query, replace_rows

SEASON_URL = "https://football-data.co.uk/mmz4281/{code}/E0.csv"
UPCOMING_URL = "https://football-data.co.uk/fixtures.csv"
ODDS_COLUMNS = ["AvgH", "AvgD", "AvgA", "Avg>2.5", "Avg<2.5"]

# football-data club name -> FPL short name (stable across seasons)
CLUB_CODES = {
    "Arsenal": "ARS", "Aston Villa": "AVL", "Bournemouth": "BOU", "Brentford": "BRE", "Brighton": "BHA",
    "Burnley": "BUR", "Chelsea": "CHE", "Coventry": "COV", "Crystal Palace": "CRY", "Everton": "EVE",
    "Fulham": "FUL", "Hull": "HUL", "Ipswich": "IPS", "Leeds": "LEE", "Leicester": "LEI", "Liverpool": "LIV",
    "Man City": "MCI", "Man United": "MUN", "Newcastle": "NEW", "Nott'm Forest": "NFO", "Southampton": "SOU",
    "Sunderland": "SUN", "Tottenham": "TOT", "West Ham": "WHU", "Wolves": "WOL",
}


def _read(path, source: str) -> pd.DataFrame:
    """Keep only the columns we use (the files have over 100)."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    if "Div" in df.columns:
        df = df[df.Div == "E0"]
    return df[["HomeTeam", "AwayTeam", *ODDS_COLUMNS]].assign(source=source)


def load_odds(settings: Settings, con, season: str) -> dict:
    """Write the `odds` table for one season: one row per fixture with odds-implied λ."""
    code = season[2:4] + season[5:7]  # "2025-26" -> "2526"
    folder = settings.cache_dir / "football-data"
    current = season == Settings.current_season
    frames = [_read(download(SEASON_URL.format(code=code),
                    folder / f"E0_{code}.csv", refresh=current), "result")]
    if current:
        frames.append(_read(download(UPCOMING_URL, folder /
                      "fixtures.csv", refresh=True), "upcoming"))
    raw = pd.concat(frames, ignore_index=True).dropna(subset=ODDS_COLUMNS)

    teams = query(
        con, "select team_id, short_name from teams where season = ?", [season])
    team_id = dict(zip(teams.short_name, teams.team_id))
    raw["team_h"] = raw.HomeTeam.map(CLUB_CODES).map(team_id)
    raw["team_a"] = raw.AwayTeam.map(CLUB_CODES).map(team_id)
    unmapped = raw[raw.team_h.isna() | raw.team_a.isna()]
    if not unmapped.empty:
        names = sorted(set(unmapped.HomeTeam) | set(unmapped.AwayTeam))
        raise ValueError(f"Add these clubs to CLUB_CODES: {names}")

    fixtures = query(
        con, "select fixture_id, gw, team_h, team_a from fixtures where season = ?", [season])
    raw = raw.astype({"team_h": int, "team_a": int}).merge(
        fixtures, on=["team_h", "team_a"])
    raw = raw.sort_values("source").drop_duplicates(
        "fixture_id", keep="first")  # "result" wins

    rates = [rates_from_odds(*row)
             for row in raw[ODDS_COLUMNS].itertuples(index=False)]
    odds = pd.DataFrame(
        {
            "season": season,
            "fixture_id": raw.fixture_id.to_numpy(),
            "gw": raw.gw.to_numpy(),
            "team_h": raw.team_h.to_numpy(),
            "team_a": raw.team_a.to_numpy(),
            "lambda_h": [r[0] for r in rates],
            "lambda_a": [r[1] for r in rates],
            "source": raw.source.to_numpy(),
        }
    )
    replace_rows(con, "odds", odds, season=season)
    return {"season": season, "fixtures": len(odds), "upcoming": int((odds.source == "upcoming").sum())}
