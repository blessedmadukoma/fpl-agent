"""Checks that compare our code with the official numbers."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from fpl.scoring import Rules, score
from fpl.storage import query, table_exists


@dataclass
class ScoringCheck:
    season: str
    source: str
    checked: int
    skipped: int
    mismatches: pd.DataFrame


def load_rules(con, season: str) -> Rules:
    game_config = query(
        con, "select game_config from rules where season = ?", [season])
    if game_config.empty:
        raise LookupError(
            f"No scoring rules stored for {season}. Run the loader first.")
    return Rules.from_game_config(json.loads(game_config.iloc[0, 0]))


def check_scoring(con, season: str) -> ScoringCheck:
    """Recompute every player's points and list the rows that differ from FPL's total_points.

    Uses per-fixture rows where we have them (history), else GW rows with one fixture.
    Floors (goals conceded, saves) apply per fixture, so double-GW totals cannot be checked.
    """
    rules = load_rules(con, season)
    if table_exists(con, "player_fixture") and _has_season(con, "player_fixture", season):
        rows, source, skipped = query(
            con, "select * from player_fixture where season = ?", [season]), "player_fixture", 0
    else:
        all_rows = query(
            con, "select * from player_gw where season = ?", [season])
        rows = all_rows[all_rows.n_fixtures == 1]
        source, skipped = "player_gw", len(all_rows) - len(rows)

    ours = rows.apply(lambda r: score(
        r.to_dict(), r["position"], rules), axis=1)
    bad = rows.assign(ours=ours)[ours != rows["total_points"]]
    columns = ["gw", "element", "position", "minutes", "total_points", "ours"]
    return ScoringCheck(season, source, len(rows), skipped, bad[columns])


def _has_season(con, table: str, season: str) -> bool:
    return query(con, f"select count(*) as n from {table} where season = ?", [season]).n.iloc[0] > 0
