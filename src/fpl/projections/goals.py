"""Goal-rate maths: bookmaker odds -> expected goals per team (λ), and Poisson helpers."""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

MAX_GOALS = 10


def remove_margin(odds: list[float]) -> np.ndarray:
    """Decimal odds -> probabilities that sum to 1 (proportional method)."""
    implied = 1 / np.asarray(odds, dtype=float)
    return implied / implied.sum()


def outcome_probabilities(lambda_home: float, lambda_away: float) -> tuple[float, float, float, float]:
    """P(home win), P(draw), P(away win), P(over 2.5 goals) under independent Poisson goals."""
    goals = np.arange(MAX_GOALS + 1)
    grid = np.outer(poisson.pmf(goals, lambda_home),
                    poisson.pmf(goals, lambda_away))
    total = np.add.outer(goals, goals)
    return float(np.tril(grid, -1).sum()), float(np.trace(grid)), float(np.triu(grid, 1).sum()), float(grid[total >= 3].sum())


def rates_from_odds(home: float, draw: float, away: float, over25: float, under25: float) -> tuple[float, float]:
    """Find (λ_home, λ_away) whose Poisson probabilities best match the market."""
    target = np.append(remove_margin(
        [home, draw, away]), remove_margin([over25, under25])[0])

    def loss(log_rates: np.ndarray) -> float:
        return float(np.sum((np.array(outcome_probabilities(*np.exp(log_rates))) - target) ** 2))

    result = minimize(loss, np.log(
        [1.4, 1.1]), method="Nelder-Mead", options={"xatol": 1e-5, "fatol": 1e-10})
    lambda_home, lambda_away = np.exp(result.x)
    return float(lambda_home), float(lambda_away)


def expected_floor(rate: np.ndarray | float, per: int) -> np.ndarray:
    """E[floor(N / per)] for N ~ Poisson(rate). Used for goals conceded (per 2) and saves (per 3)."""
    k = np.arange(MAX_GOALS * 3 + 1)
    pmf = poisson.pmf(k[:, None], np.atleast_1d(rate)[None, :])
    return (pmf * (k // per)[:, None]).sum(axis=0)
