"""Put the pieces together: projections for the next GWs, your squad, and the solver."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from fpl.config import Settings
from fpl.context import GwContext
from fpl.fplapi import FplClient
from fpl.optimise.chip_decision import ChipDecision, assess_chips, chip_projection_gws
from fpl.optimise.solver import Plan, SolverSettings, optimise
from fpl.projections import registry
from fpl.projections.horizon import horizon_table
from fpl.team_state import SquadPlayer, TeamState, current_team


@dataclass
class Recommendation:
    ctx: GwContext
    team: TeamState
    ep: pd.DataFrame
    plan: Plan          # transfers allowed in every GW
    # no transfer this GW (roll it), transfers allowed later
    hold: Plan
    threshold: float
    chip_decision: ChipDecision | None = None

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


def recommend_from_projections(
    ctx: GwContext,
    team: TeamState,
    ep: pd.DataFrame,
    settings: SolverSettings,
    threshold: float,
    chip_ep: pd.DataFrame | None = None,
) -> Recommendation:
    """Compare transfers with holding the first GW using prepared projections."""
    plan = optimise(ep, ctx.state, team, settings)
    hold = optimise(ep, ctx.state, team, replace(settings, hold_first_gw=True))

    result = Recommendation(ctx, team, ep, plan, hold, threshold)
    first = result.chosen.gws[0]
    prices = ctx.state.set_index("element").now_cost
    original = {player.element: player for player in team.squad}
    squad = tuple(
        original[element] if element in original else
        SquadPlayer(element, int(prices.at[element]), int(prices.at[element]))
        for element in first.xi + first.bench
    )
    bank = team.bank + sum(team.selling_prices()[p] for p in first.sell) - sum(
        int(prices.at[p]) for p in first.buy)
    selected_team = replace(team, squad=squad, bank=bank,
                            free_transfers=max(0, team.free_transfers - len(first.buy)))
    result.chip_decision = assess_chips(
        chip_ep if chip_ep is not None else ep, ctx.state, selected_team,
    )
    return result


def recommend(con, client: FplClient, entry_id: int, model: str = "shrunk_blend", horizon: int = 4,
              threshold: float = 2.0, settings: SolverSettings = SolverSettings()) -> Recommendation:
    ctx, team = current_team(con, client, entry_id)
    gws = [g for g in range(ctx.gw, ctx.gw + horizon) if g <= 38]
    chip_gws = chip_projection_gws(team, ctx.gw)
    ep = horizon_table(ctx, registry.build(
        model, con, Settings.current_season, first_gw=ctx.gw), sorted(set(gws + chip_gws)))

    recommendation = recommend_from_projections(
        ctx, team, ep[gws], settings, threshold,
        chip_ep=ep[chip_gws] if chip_gws else None)

    return recommendation
