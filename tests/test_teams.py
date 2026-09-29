import numpy as np
import pandas as pd

from fpl.projections.goals import expected_floor, outcome_probabilities, rates_from_odds
from fpl.projections.teams import fit_ratings


def test_odds_inversion_recovers_the_goal_rates():
    home, draw, away, over = outcome_probabilities(1.8, 0.9)
    lambda_h, lambda_a = rates_from_odds(
        1 / home, 1 / draw, 1 / away, 1 / over, 1 / (1 - over))
    assert abs(lambda_h - 1.8) < 0.01 and abs(lambda_a - 0.9) < 0.01


def test_expected_floor_matches_simulation():
    rng = np.random.default_rng(0)
    draws = rng.poisson(2.5, 200_000)
    assert abs(expected_floor(2.5, 2)[0] - (draws // 2).mean()) < 0.01


def test_ratings_recover_a_strong_attack():
    teams = [1, 2, 3, 4]
    attack = {1: 0.4, 2: 0.0, 3: 0.0, 4: -0.4}
    rows = [
        {"team_h": h, "team_a": a, "weight": 1.0,
         "lambda_h": np.exp(0.2 + 0.1 + attack[h]), "lambda_a": np.exp(0.2 + attack[a])}
        for h in teams for a in teams if h != a
    ]
    ratings = fit_ratings(pd.DataFrame(rows), teams, ridge=0.01)
    assert ratings.attack[1] > ratings.attack[2] > ratings.attack[4]
    assert abs(ratings.home - 0.1) < 0.02
