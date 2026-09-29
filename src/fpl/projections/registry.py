"""Look up a projection model by name, so the CLI, backtest and solver can switch models.

Baselines need no training. The full model is trained on data from before `first_gw`,
so the same call works for a backtest (first_gw = 20) and for the live GW.
"""

from __future__ import annotations

from fpl.config import Settings
from fpl.projections.baseline import BASELINES, Projector

MODELS = [*BASELINES, "full"]


def build(name: str, con=None, season: str = Settings.current_season, first_gw: int = 1) -> Projector:
    if name in BASELINES:
        return BASELINES[name]
    if name == "full":
        from fpl.projections.points import build as build_points

        previous = Settings.history_season if season == Settings.current_season else None
        return build_points(con, season, first_gw, previous)
    raise SystemExit(
        f"Unknown model '{name}'. Choose from: {', '.join(MODELS)}")
