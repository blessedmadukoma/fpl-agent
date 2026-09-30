"""Chip values per GW, so each chip can be planned for its best GW before it expires.

For each GW (01-reference.md H.10):
- Triple Captain: the captain's expected points (the extra 1×)
- Bench Boost: the expected points of your 4 bench players
- Free Hit: best legal squad's XI for that GW − your own XI, both with captain
All values use your current squad; they move as your squad changes, so rerun weekly.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from fpl.optimise.solver import SolverSettings, optimise
from fpl.team_state import TeamState, free_transfers


def chip_values(ep: pd.DataFrame, players: pd.DataFrame, team: TeamState) -> pd.DataFrame:
    rows = []

    for gw in ep.columns:
        single = ep[[gw]]
        own = optimise(single, players, team, SolverSettings(
            allow_transfers=False)).gws[0]
        free_hit_team = replace(team, free_transfers=15)
        best = optimise(single, players, free_hit_team,
                        SolverSettings(max_free_transfers=15)).gws[0]
        rows.append({
            "gw": gw,
            "your_xi": own.expected_points,
            "triple_captain": single.at[own.captain, gw],
            "bench_boost": sum(single.at[p, gw] for p in own.bench),
            "free_hit": best.expected_points - own.expected_points
        })

    return pd.DataFrame(rows)


def best_gws(values: pd.DataFrame, chips: list[str]) -> dict[str, int]:
    """The highest-value GW for each chip you still have"""
    return {chip: int(values.loc[values[chip].idxmax(), "gw"]) for chip in chips}
