"""Replay a season GW by GW: project with only what was known, then compare with reality."""

from __future__ import annotations

import pandas as pd

from fpl.backtest import metrics
from fpl.context import load_context
from fpl.projections.baseline import Projector
from fpl.storage import query

POOL_R = "regular starters (3+ starts in previous 4 GWs)"
POOL_O = "owned by 1%+ at the deadline"
POOL_ALL = "all players"


def replay(con, season: str, projector: Projector, gws: range) -> pd.DataFrame:
    """One row per player per GW: projection `ep`, realised `pts` and pool flags."""
    outcomes = query(
        con, "select gw, element, total_points as pts, starts from player_gw where season = ?", [season])
    pools = pool_flags(outcomes)
    frames = []
    for gw in gws:
        ctx = load_context(con, season, gw)
        ep = projector(ctx).rename("ep").rename_axis("element").reset_index()
        ep["gw"] = gw
        ep = ep.merge(ctx.state[["element", "selected"]], on="element")
        frames.append(ep)
    projected = pd.concat(frames, ignore_index=True)
    # Inner join: a player with no fixture that GW has no outcome row and is left out.
    frame = projected.merge(
        outcomes[["gw", "element", "pts"]], on=["gw", "element"])
    frame = frame.merge(pools, on=["gw", "element"], how="left")
    frame["pool_R"] = frame.pool_R.fillna(False).astype(bool)
    frame["pool_O"] = frame.selected >= 1.0
    return frame


def pool_flags(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Pool R membership per (gw, element), using only earlier GWs."""
    df = outcomes.sort_values(["element", "gw"]).copy()
    started = (df.starts > 0).astype(int)
    df["starts_last4"] = started.groupby(df.element).transform(
        lambda s: s.shift(1).rolling(4, min_periods=4).sum()
    )
    df["pool_R"] = df.starts_last4 >= 3
    return df[["gw", "element", "pool_R"]]


def summarise(frame: pd.DataFrame, k: int = 15) -> tuple[pd.DataFrame, dict]:
    """The metrics table used throughout the guide, plus the top-k check."""
    rows = []
    everyone = pd.Series(True, index=frame.index)
    for name, mask in [(POOL_R, frame.pool_R), (POOL_O, frame.pool_O), (POOL_ALL, everyone)]:
        part = frame[mask]
        rows.append(
            {
                "pool": name,
                "n": len(part),
                "rmse": metrics.rmse(part.ep, part.pts),
                "bias": metrics.bias(part.ep, part.pts),
                "rho": metrics.mean_rank_correlation(part, "ep", "pts"),
            }
        )
    projected, realised = metrics.top_k(frame, "ep", "pts", k=k)
    table = pd.DataFrame(rows)
    top = {"top_k": k, "projected": projected, "realised": realised}
    return table, top
