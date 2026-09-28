"""Turn a one-GW projection into a table of expected points for several GWs."""

from __future__ import annotations

import pandas as pd

from fpl.context import GwContext
from fpl.projections.baseline import Projector


def fixture_counts(fixtures: pd.DataFrame, gws: list[int]) -> pd.DataFrame:
    """Number of fixtures per team per GW (0 = blank, 2 = double)."""
    rows = []

    for side in ("team_h", "team_a"):
        part = fixtures[fixtures.gw.isin(gws)][["gw", side]].rename(
            columns={side: "team"})
        rows.append(part)

    counts = pd.concat(rows).value_counts().rename("n").reset_index()
    grid = pd.MultiIndex.from_product(
        [sorted(set(fixtures.team_h)), gws], names=["team", "gw"])

    return counts.set_index(["team", "gw"]).reindex(grid, fill_value=0).n.unstack("gw")


def horizon_table(ctx: GwContext, projector: Projector, gws: list[int]) -> pd.DataFrame:
    """Players × GWs of expected points: per fixture if the model can, else repeated."""
    if hasattr(projector, "horizon"):
        return projector.horizon(ctx, gws)

    return repeat_over_horizon(ctx, projector, gws)


def repeat_over_horizon(ctx: GwContext, projector: Projector, gws: list[int]) -> pd.DataFrame:
    """Expected points per player (rows) per GW (columns): the one-GW value × fixture count.

    This is what the skeleton does: it has no view of future opponents. The full model in
    part 2 projects each fixture instead.
    """
    per_gw = projector(ctx)
    counts = fixture_counts(ctx.fixtures, gws)
    team = ctx.state.set_index("element").team
    table = counts.reindex(team.to_numpy()).set_axis(team.index, axis=0)
    return table.mul(per_gw.reindex(team.index), axis=0).fillna(0.0)
