"""Load the current season from the live FPL API into DuckDB."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from fpl.config import Settings
from fpl.fplapi import FplClient
from fpl.storage import replace_rows

# FPL element_type -> position
POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# Per-player stats we keep from event/{gw}/live. Numeric strings (xG) are cast to float.
LIVE_STATS = [
    "minutes", "starts", "total_points", "goals_scored", "assists", "clean_sheets",
    "goals_conceded", "saves", "bonus", "bps", "defensive_contribution",
    "expected_goals", "expected_assists", "expected_goals_conceded",
    "yellow_cards", "red_cards", "own_goals", "penalties_saved", "penalties_missed",
]


def update_current(client: FplClient, con) -> dict:
    """Fetch bootstrap, fixtures and every finished GW; write them for CURRENT_SEASON."""
    boot = client.bootstrap()
    season = Settings.current_season

    events = events_frame(boot, season)
    teams = teams_frame(boot, season)
    fixtures = fixtures_frame(client.fixtures(), season)
    players = players_frame(boot, season)
    finished = events.loc[events.finished, "gw"].tolist()
    player_gw = pd.concat(
        [player_gw_frame(client.live(gw), gw, players, season) for gw in finished])
    next_gw = int(events.loc[~events.finished, "gw"].min())
    state = state_frame(boot, season, next_gw,
                        snapshot_time=datetime.now(timezone.utc))

    rules = pd.DataFrame(
        [{"season": season, "game_config": json.dumps(boot["game_config"])}])
    for table, df in [("events", events), ("teams", teams), ("fixtures", fixtures),
                      ("player_gw", player_gw), ("rules", rules)]:
        replace_rows(con, table, df, season=season)
    replace_rows(con, "state", state, season=season, gw=next_gw)

    return {
        "season": season,
        "players": len(players),
        "finished_gws": finished,
        "player_gw_rows": len(player_gw),
        "next_gw": next_gw,
        "next_deadline": events.loc[events.gw == next_gw, "deadline"].iloc[0],
    }


def events_frame(boot: dict, season: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": season,
            "gw": e["id"],
            "deadline": pd.Timestamp(e["deadline_time"]),
            "finished": bool(e["finished"]),
        }
        for e in boot["events"]
    )


def teams_frame(boot: dict, season: str) -> pd.DataFrame:
    return pd.DataFrame(
        {"season": season,
            "team_id": t["id"], "name": t["name"], "short_name": t["short_name"]}
        for t in boot["teams"]
    )


def fixtures_frame(fixtures: list[dict], season: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": season,
            "fixture_id": f["id"],
            "gw": f["event"],
            "kickoff": pd.Timestamp(f["kickoff_time"]) if f["kickoff_time"] else pd.NaT,
            "team_h": f["team_h"],
            "team_a": f["team_a"],
            "goals_h": f["team_h_score"],
            "goals_a": f["team_a_score"],
            "finished": bool(f["finished"]),
        }
        for f in fixtures
    )


def players_frame(boot: dict, season: str) -> pd.DataFrame:
    """Current snapshot of every player (prices, status, flags)."""
    return pd.DataFrame(_player_row(p, season) for p in boot["elements"])


def state_frame(boot: dict, season: str, gw: int, snapshot_time) -> pd.DataFrame:
    """Pre-deadline state for one GW: the inputs a projection may use for that GW. Crucial as this is what a model may use for a GW"""
    df = players_frame(boot, season)
    df.insert(1, "gw", gw)
    df["snapshot_time"] = pd.Timestamp(snapshot_time)
    return df


def _player_row(p: dict, season: str) -> dict:
    return {
        "season": season,
        "element": p["id"],
        "code": p["code"],
        "web_name": p["web_name"],
        "team": p["team"],
        "position": POSITIONS[p["element_type"]],
        "now_cost": p["now_cost"],
        "cost_change_start": p["cost_change_start"],
        "status": p["status"],
        "chance": p["chance_of_playing_next_round"],
        "news": p["news"],
        "news_added": pd.Timestamp(p["news_added"]) if p.get("news_added") else pd.NaT,
        "ep_next": float(p["ep_next"] or 0),
        "form": float(p["form"] or 0),
        "ppg": float(p["points_per_game"] or 0),
        "selected": float(p["selected_by_percent"] or 0),
        "penalties_order": p.get("penalties_order"),
        "loan_ineligible_gws": ",".join(
            str(r["gameweek"]) for r in p.get("scout_risks") or [] if r.get("property") == "loan_ineligible"
        ),
    }


def player_gw_frame(live: dict, gw: int, players: pd.DataFrame, season: str) -> pd.DataFrame:
    """One row per player per finished GW, with GW-total stats."""
    rows = []
    for element in live["elements"]:
        # the player's team had no fixture (blank GW)
        if not element["explain"]:
            continue
        stats = element["stats"]
        row = {"season": season, "gw": gw,
               "element": element["id"], "n_fixtures": len(element["explain"])}
        row.update({key: float(stats[key]) for key in LIVE_STATS})
        rows.append(row)
    df = pd.DataFrame(rows)
    meta = players[["element", "position", "team"]]
    return df.merge(meta, on="element", how="left")
