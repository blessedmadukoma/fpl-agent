"""Expected goals for every fixture in the horizon, for clean sheets and opponent strength.

Two sources (01-reference.md H.4):
- the next GW: bookmaker odds, when football-data has them;
- later GWs, or when odds are missing: team ratings fitted to the odds-implied λ of past
  fixtures. Fitting to odds rather than to goals gives far less noisy ratings.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fpl.context import GwContext
from fpl.storage import query

DECAY_PER_DAY = 0.005   # weight halves about every 140 days
RIDGE = 2.0             # pulls team ratings towards average when data is thin


@dataclass(frozen=True)
class TeamRatings:
    base: float
    home: float
    attack: dict[int, float]
    defence: dict[int, float]

    def rates(self, team_h: int, team_a: int) -> tuple[float, float]:
        a, d = self.attack, self.defence
        lambda_h = np.exp(self.base + self.home +
                          a.get(team_h, 0.0) - d.get(team_a, 0.0))
        lambda_a = np.exp(self.base + a.get(team_a, 0.0) - d.get(team_h, 0.0))
        return float(lambda_h), float(lambda_a)

    def average_rate(self, team: int) -> float:
        """λ against an average opponent, with half the home advantage."""
        return float(np.exp(self.base + self.home / 2 + self.attack.get(team, 0.0)))


def fit_ratings(matches: pd.DataFrame, teams: list[int], ridge: float = RIDGE) -> TeamRatings:
    """Weighted ridge regression of log λ on attack, defence and home advantage.

    `matches` has team_h, team_a, lambda_h, lambda_a and weight.
    """
    index = {team: i for i, team in enumerate(teams)}
    n = len(teams)
    rows, targets, weights = [], [], []
    for m in matches.itertuples():
        for attacker, defender, is_home, rate in [(m.team_h, m.team_a, 1, m.lambda_h), (m.team_a, m.team_h, 0, m.lambda_a)]:
            row = np.zeros(2 + 2 * n)
            row[0], row[1] = 1.0, is_home
            row[2 + index[attacker]] = 1.0
            row[2 + n + index[defender]] = -1.0
            rows.append(row)
            targets.append(np.log(rate))
            weights.append(m.weight)
    x, y, w = np.array(rows), np.array(targets), np.sqrt(np.array(weights))
    penalty = np.hstack([np.zeros((2 * n, 2)), np.sqrt(ridge) * np.eye(2 * n)])
    design = np.vstack([x * w[:, None], penalty])
    response = np.concatenate([y * w, np.zeros(2 * n)])
    coef, *_ = np.linalg.lstsq(design, response, rcond=None)
    attack = {t: coef[2 + i] for t, i in index.items()}
    defence = {t: coef[2 + n + i] for t, i in index.items()}
    return TeamRatings(base=coef[0], home=coef[1], attack=attack, defence=defence)


def fixture_rates(con, ctx: GwContext, gws: list[int]) -> pd.DataFrame:
    """λ for every fixture of `gws`: odds for ctx.gw where available, ratings otherwise."""
    odds = query(
        con, "select * from odds where season = ? and gw <= ?", [ctx.season, ctx.gw])
    ratings = ratings_at(ctx, odds)
    upcoming = ctx.fixtures[ctx.fixtures.gw.isin(
        gws)][["fixture_id", "gw", "team_h", "team_a"]].copy()
    rated = [ratings.rates(h, a)
             for h, a in zip(upcoming.team_h, upcoming.team_a)]
    upcoming["lambda_h"] = [r[0] for r in rated]
    upcoming["lambda_a"] = [r[1] for r in rated]
    upcoming["source"] = "ratings"

    market = odds[odds.gw == ctx.gw].set_index("fixture_id")
    has_odds = upcoming.fixture_id.isin(market.index)
    for column in ("lambda_h", "lambda_a"):
        upcoming.loc[has_odds, column] = upcoming.loc[has_odds,
                                                      "fixture_id"].map(market[column])
    upcoming.loc[has_odds, "source"] = "odds"
    upcoming["avg_h"] = upcoming.team_h.map(ratings.average_rate)
    upcoming["avg_a"] = upcoming.team_a.map(ratings.average_rate)
    return upcoming.reset_index(drop=True)


def ratings_at(ctx: GwContext, odds: pd.DataFrame) -> TeamRatings:
    """Ratings from the odds of fixtures played before ctx.gw (no leakage)."""
    past = odds[odds.gw < ctx.gw].merge(
        ctx.fixtures[["fixture_id", "kickoff"]], on="fixture_id")
    days_ago = (ctx.deadline - past.kickoff).dt.total_seconds() / 86400
    past = past.assign(weight=np.exp(-DECAY_PER_DAY * days_ago.to_numpy()))
    return fit_ratings(past, sorted(ctx.teams.team_id))


def team_view(rates: pd.DataFrame) -> pd.DataFrame:
    """One row per team per fixture: own λ (for attack) and opponent λ (for clean sheets)."""
    home = rates.rename(columns={"team_h": "team", "team_a": "opponent", "lambda_h": "lambda_for",
                                 "lambda_a": "lambda_against", "avg_h": "lambda_avg"})
    away = rates.rename(columns={"team_a": "team", "team_h": "opponent", "lambda_a": "lambda_for",
                                 "lambda_h": "lambda_against", "avg_a": "lambda_avg"})
    columns = ["fixture_id", "gw", "team", "opponent",
               "lambda_for", "lambda_against", "lambda_avg", "source"]
    view = pd.concat([home.assign(home=True), away.assign(home=False)])[
        columns + ["home"]]
    view["p_clean_sheet"] = np.exp(-view.lambda_against)
    view["attack_factor"] = view.lambda_for / view.lambda_avg
    return view.reset_index(drop=True)
