"""What was knowable at a GW deadline. Every projection takes one of these as input.

The leakage rule lives here and nowhere else: `history` only holds GWs before `gw`, and
`state` is the last snapshot before the deadline. A model that only reads a GwContext
cannot see the future.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fpl.config import Settings
from fpl.storage import query


@dataclass(frozen=True)
class GwContext:
    season: str
    gw: int
    deadline: pd.Timestamp
    # one row per player: status, flags, price, ep_next, ... at the deadline
    state: pd.DataFrame
    history: pd.DataFrame    # player_gw rows of this season with gw < self.gw
    # every fixture of the season (results only used for gw < self.gw)
    fixtures: pd.DataFrame
    teams: pd.DataFrame

    def past_fixtures(self) -> pd.DataFrame:
        return self.fixtures[self.fixtures.gw < self.gw]


def load_context(con, season: str, gw: int) -> GwContext:
    deadline = query(
        con, "select deadline from events where season = ? and gw = ?", [season, gw])
    state = query(
        con, "select * from state where season = ? and gw = ?", [season, gw])
    if deadline.empty or state.empty:
        raise LookupError(
            f"No deadline or pre-deadline state for {season} GW{gw}. Run `fpl update`.")
    history = query(
        con, "select * from player_gw where season = ? and gw < ? order by gw", [season, gw])
    fixtures = query(con, "select * from fixtures where season = ?", [season])
    teams = query(con, "select * from teams where season = ?", [season])
    return GwContext(season, gw, deadline.deadline.iloc[0], state, history, fixtures, teams)


def next_gw(con, season: str = Settings.current_season) -> int:
    """The first GW that has not finished: the one you are picking a team for."""
    events = query(
        con, "select gw from events where season = ? and not finished order by gw", [season])
    return int(events.gw.iloc[0])
