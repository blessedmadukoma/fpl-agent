"""Look up a projection model by name, so the CLI, backtest and solver can switch models."""

from __future__ import annotations

from fpl.config import Settings
from fpl.projections.baseline import BASELINES, Projector

MODELS = list(BASELINES)


def build(name: str, con=None, season: str = Settings.current_season, first_gw: int = 1) -> Projector:
    """Return the model called `name`. Baselines need no training; step 10 adds a trained model."""
    if name in BASELINES:
        return BASELINES[name]
    raise SystemExit(
        f"Unknown model '{name}'. Choose from: {', '.join(MODELS)}")
