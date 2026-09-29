"""How good are the clean-sheet probabilities, by how far ahead they are made?"""

from __future__ import annotations

import pandas as pd

from fpl.backtest import metrics
from fpl.context import load_context
from fpl.projections.teams import fixture_rates, team_view


def clean_sheet_backtest(con, season: str, gws: range, horizon: int = 6) -> pd.DataFrame:
    rows = []
    for gw in gws:
        ctx = load_context(con, season, gw)
        ahead = [g for g in range(gw, gw + horizon) if g <= 38]
        view = team_view(fixture_rates(con, ctx, ahead))
        results = ctx.fixtures[["fixture_id", "goals_h", "goals_a", "team_h"]]
        view = view.merge(results, on="fixture_id")
        conceded = view.goals_a.where(view.team == view.team_h, view.goals_h)
        rows.append(view.assign(
            made_at=gw, clean_sheet=(conceded == 0).astype(float)))
    frame = pd.concat(rows, ignore_index=True)
    frame["gws_ahead"] = frame.gw - frame.made_at
    base_rate = frame.clean_sheet.mean()

    summary = []
    for (ahead, source), part in frame.groupby(["gws_ahead", "source"]):
        brier = metrics.brier(part.p_clean_sheet, part.clean_sheet)
        constant = metrics.brier(
            pd.Series(base_rate, index=part.index), part.clean_sheet)
        summary.append({"gws_ahead": ahead, "source": source, "n": len(part), "brier": brier,
                        "constant_rate_brier": constant, "skill": 1 - brier / constant})
    return pd.DataFrame(summary)
