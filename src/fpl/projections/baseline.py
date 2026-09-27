"""Simple projections that need no model. They are the numbers every model must beat.

A projector takes a GwContext and returns expected points for that GW, one value per
player, as a Series indexed by element id.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from fpl.context import GwContext

Projector = Callable[[GwContext], pd.Series]


def _by_element(ctx: GwContext, values) -> pd.Series:
    return pd.Series(values.to_numpy(dtype=float), index=ctx.state.element.to_numpy(), name="ep")


def availability_factor(state: pd.DataFrame) -> pd.Series:
    """FPL's chance-of-playing flag as a factor: 1 when there is no flag."""
    return (state.chance.astype(float) / 100).fillna(1.0)


def ep_next(ctx: GwContext) -> pd.Series:
    """FPL's own projection (about form × chance of playing)."""
    return _by_element(ctx, ctx.state.ep_next)


def points_per_game(ctx: GwContext) -> pd.Series:
    return _by_element(ctx, ctx.state.ppg)


def form(ctx: GwContext) -> pd.Series:
    return _by_element(ctx, ctx.state.form)


def zero(ctx: GwContext) -> pd.Series:
    return _by_element(ctx, ctx.state.ep_next * 0)


def blend(ctx: GwContext) -> pd.Series:
    """0.5 × ep_next + 0.5 × PPG × flag. In the 2025/26 replay it beats both of its parts."""
    ppg_available = ctx.state.ppg * availability_factor(ctx.state)
    return _by_element(ctx, 0.5 * ctx.state.ep_next + 0.5 * ppg_available)


# Prior weight, in appearances. Tuned on the 2025/26 replay: k = 4 gives a bias near zero
# and halves the over-projection of the top 15 players per GW (01-reference.md §I).
SHRINK_APPEARANCES = 4


def shrunk_blend(ctx: GwContext, k: float = SHRINK_APPEARANCES) -> pd.Series:
    """The blend, pulled towards a typical player of the same position.

    A player with n appearances gets weight n / (n + k) on his own numbers. The prior is the
    position's mean points per appearance × his start rate × his availability flag.
    """
    raw = blend(ctx)
    played = ctx.history[ctx.history.minutes > 0]
    appearances = played.groupby(
        "element").size().reindex(raw.index, fill_value=0)
    per_appearance = played.groupby("position").total_points.mean()
    start_rate = (ctx.history.starts > 0).groupby(
        ctx.history.element).mean().reindex(raw.index, fill_value=0.0)
    state = ctx.state.set_index("element")
    prior = state.position.map(per_appearance).fillna(
        0.0) * start_rate * availability_factor(state)
    return ((appearances * raw + k * prior) / (appearances + k)).rename("ep")


BASELINES: dict[str, Projector] = {
    "shrunk_blend": shrunk_blend,
    "blend": blend,
    "ep_next": ep_next,
    "ppg": points_per_game,
    "form": form,
    "zero": zero,
}
