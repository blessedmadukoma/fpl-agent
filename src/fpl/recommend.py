"""Put the pieces together: projections for the next GWs, your squad, and the solver."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from fpl.config import Settings
from fpl.context import GwContext
from fpl.fplapi import FplClient
from fpl.optimise.solver import Plan, SolverSettings, optimise
from fpl.projections import registry
from fpl.projections.horizon import horizon_table
from fpl.team_state import TeamState, current_team


@dataclass
class Recommendation:
    ctx: GwContext
    team: TeamState
    ep: pd.DataFrame
    plan: Plan          # transfers allowed in every GW
    # no transfer this GW (roll it), transfers allowed later
    hold: Plan
    threshold: float

    @property
    def gain(self) -> float:
        return self.plan.objective - self.hold.objective

    @property
    def make_transfers(self) -> bool:
        first = self.plan.gws[0]
        return bool(first.buy) and self.gain >= self.threshold

    @property
    def chosen(self) -> Plan:
        return self.plan if self.make_transfers else self.hold


def recommend(con, client: FplClient, entry_id: int, model: str = "shrunk_blend", horizon: int = 4,
              threshold: float = 2.0, settings: SolverSettings = SolverSettings()) -> Recommendation:
    ctx, team = current_team(con, client, entry_id)
    gws = [g for g in range(ctx.gw, ctx.gw + horizon) if g <= 38]
    ep = horizon_table(ctx, registry.build(
        model, con, Settings.current_season, first_gw=ctx.gw), gws)

    plan = optimise(ep, ctx.state, team, settings)
    hold = optimise(ep, ctx.state, team, replace(settings, hold_first_gw=True))

    return Recommendation(ctx, team, ep, plan, hold, threshold)
