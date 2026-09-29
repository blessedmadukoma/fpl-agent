"""The full points model: expected points per player per fixture, built from components.

E[pts] = appearance + goals + assists + clean sheet − goals conceded + saves
         + defensive contribution + bonus − cards              (01-reference.md H.1)

Minutes come from the minutes model, goal rates from the team model, and each player's
per-90 rates are shrunk towards his position's average (H.2). Non-linear terms (clean
sheets, goals conceded, saves, DefCon) are computed per minutes scenario: 60+ or 1-59.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import nbinom

from fpl.checks import load_rules
from fpl.context import GwContext
from fpl.projections import minutes as minutes_model
from fpl.projections.goals import expected_floor
from fpl.projections.teams import fixture_rates, team_view
from fpl.scoring import DEFCON_THRESHOLD, Rules
from fpl.storage import query

PRIOR_90S = 6.0           # shrinkage strength k, in 90-minute matches (H.2)
PREVIOUS_SEASON_WEIGHT = 0.5  # last season's minutes count half
# negative-binomial φ, estimated per player on 2025/26 (close to Poisson)
DEFCON_DISPERSION = 16.0
RATE_STATS = ["expected_goals", "expected_assists",
              "defensive_contribution", "saves", "yellow_cards"]


@dataclass
class PointsModel:
    con: object
    minutes: minutes_model.MinutesModel
    # last season's totals per player code (may be empty)
    previous: pd.DataFrame
    rules: Rules

    def project(self, ctx: GwContext, gws: list[int]) -> pd.DataFrame:
        """One row per player per fixture in `gws`, with every component and `ep`."""
        players = ctx.state.set_index("element")[["code", "team", "position"]]
        mins = self.minutes.predict(minutes_model.features(ctx))
        rates = shrunk_rates(ctx.history, players, self.previous)
        fixtures = team_view(fixture_rates(self.con, ctx, gws))

        df = players.join(mins).join(
            rates).reset_index().merge(fixtures, on="team")
        df["m60"], df["mshort"] = self.minutes.minutes_if_60, self.minutes.minutes_if_short
        return add_components(df, self.rules, fit_bonus(ctx.history))

    def __call__(self, ctx: GwContext) -> pd.Series:
        """Projector interface (one GW), so the backtest can score this model."""
        rows = self.project(ctx, [ctx.gw])
        return rows.groupby("element").ep.sum().reindex(ctx.state.element, fill_value=0.0).rename("ep")

    def horizon(self, ctx: GwContext, gws: list[int]) -> pd.DataFrame:
        rows = self.project(ctx, gws)
        table = rows.pivot_table(
            index="element", columns="gw", values="ep", aggfunc="sum")
        return table.reindex(index=ctx.state.element, columns=gws).fillna(0.0)


def build(con, season: str, first_gw: int, previous_season: str | None) -> PointsModel:
    """Train on data from before `first_gw` only, so the model can be backtested honestly."""
    gws = minutes_model.training_gws(con, season, first_gw, previous_season)
    return PointsModel(
        con=con,
        minutes=minutes_model.train(con, gws),
        previous=season_totals(
            con, previous_season) if previous_season else pd.DataFrame(),
        rules=load_rules(con, season),
    )


def season_totals(con, season: str) -> pd.DataFrame:
    """Minutes and rate stats per player code for a whole season."""
    sql = f"""
        select s.code, sum(p.minutes) as minutes, {", ".join(f"sum(p.{c}) as {c}" for c in RATE_STATS)}
        from player_gw p join (select distinct element, code from state where season = ?) s using (element)
        where p.season = ? group by s.code
    """
    return query(con, sql, [season, season]).set_index("code")


def shrunk_rates(history: pd.DataFrame, players: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    """Per-90 rates: (k·prior + events) / (k + 90s played). Prior = the position's average."""
    this_season = history.groupby("element")[
        ["minutes", *RATE_STATS]].sum().reindex(players.index, fill_value=0.0)
    totals = this_season.copy()
    if not previous.empty:
        last = previous.reindex(players.code.to_numpy()).fillna(
            0.0).set_axis(players.index)
        totals = totals + PREVIOUS_SEASON_WEIGHT * last

    pooled = totals.join(players.position).groupby("position").sum()
    prior = pooled[RATE_STATS].div(pooled.minutes / 90, axis=0)
    per_player_prior = prior.reindex(
        players.position.to_numpy()).set_axis(players.index)

    nineties = totals.minutes / 90
    shrunk = (PRIOR_90S * per_player_prior +
              totals[RATE_STATS]).div(PRIOR_90S + nineties, axis=0)
    return shrunk.add_suffix("_90")


def fit_bonus(history: pd.DataFrame) -> pd.DataFrame:
    """Bonus per appearance ≈ a + b·goals + c·assists + d·clean sheet + e·(60+), per position.

    Fitted on this season only, because the BPS rules changed for 2026/27.
    """
    played = history[history.minutes > 0]
    coefficients = {}
    for position, rows in played.groupby("position"):
        x = np.column_stack([np.ones(len(rows)), rows.goals_scored, rows.assists, rows.clean_sheets,
                             (rows.minutes >= 60).astype(float)])
        coefficients[position], * \
            _ = np.linalg.lstsq(x, rows.bonus.to_numpy(), rcond=None)
    return pd.DataFrame(coefficients, index=["base", "goal", "assist", "clean_sheet", "long_play"]).T


def add_components(df: pd.DataFrame, rules: Rules, bonus: pd.DataFrame) -> pd.DataFrame:
    pos = df.position
    def points(stat): return pos.map(lambda p: rules.points(stat, p))
    per_90 = df.e_minutes / 90
    scenarios = [("p_60", "m60"), ("p_short", "mshort")]

    df["pts_appearance"] = 2 * df.p_60 + 1 * df.p_short
    df["e_goals"] = per_90 * df.expected_goals_90 * df.attack_factor
    df["e_assists"] = per_90 * df.expected_assists_90 * df.attack_factor
    df["pts_goals"] = df.e_goals * points("goals_scored")
    df["pts_assists"] = df.e_assists * points("assists")
    df["p_clean_sheet_60"] = df.p_60 * df.p_clean_sheet
    df["pts_clean_sheet"] = df.p_clean_sheet_60 * points("clean_sheets")

    conceded = sum(df[p] * expected_floor(df.lambda_against *
                   df[m] / 90, 2) for p, m in scenarios)
    df["pts_conceded"] = conceded * points("goals_conceded")
    saves = sum(df[p] * expected_floor(df.saves_90 * df[m] / 90, 3)
                for p, m in scenarios)
    df["pts_saves"] = saves * points("saves") * (pos == "GKP")

    threshold = pos.map(DEFCON_THRESHOLD).to_numpy()
    df["p_defcon"] = sum(df[p] * _p_at_least(df.defensive_contribution_90 *
                         df[m] / 90, threshold) for p, m in scenarios)
    df["pts_defcon"] = df.p_defcon * points("defensive_contribution")

    b = bonus.reindex(pos.to_numpy()).fillna(0.0).set_axis(df.index)
    df["pts_bonus"] = (b.base * (df.p_60 + df.p_short) + b.goal * df.e_goals + b.assist * df.e_assists
                       + b.clean_sheet * df.p_clean_sheet_60 + b.long_play * df.p_60).clip(lower=0)
    df["pts_cards"] = per_90 * df.yellow_cards_90 * points("yellow_cards")

    components = [c for c in df.columns if c.startswith("pts_")]
    df["ep"] = df[components].sum(axis=1)
    return df


def _p_at_least(mean: pd.Series, threshold: np.ndarray, dispersion: float = DEFCON_DISPERSION) -> np.ndarray:
    """P(X ≥ threshold) for a negative binomial with the given mean and dispersion."""
    mean = np.maximum(mean.to_numpy(dtype=float), 1e-9)
    p = dispersion / (dispersion + mean)
    return 1 - nbinom.cdf(np.minimum(threshold, 10**6) - 1, dispersion, p)
