from fpl.scoring import Rules, score

# The 2026/27 coefficients, as returned in game_config.scoring (only the keys score() uses).
RULES = Rules(
    {
        "long_play": 2, "short_play": 1, "assists": 3, "saves": 1, "bonus": 1,
        "penalties_saved": 5, "penalties_missed": -2, "yellow_cards": -1, "red_cards": -3, "own_goals": -2,
        "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
        "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
        "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
        "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
    }
)


def test_appearance_points():
    assert score({"minutes": 0}, "MID", RULES) == 0
    assert score({"minutes": 59}, "MID", RULES) == 1
    assert score({"minutes": 60}, "MID", RULES) == 2


def test_defender_clean_sheet_and_goal():
    assert score({"minutes": 90, "clean_sheets": 1,
                 "goals_scored": 1}, "DEF", RULES) == 2 + 4 + 6


def test_goals_conceded_floor_per_two():
    assert score({"minutes": 90, "goals_conceded": 3}, "GKP", RULES) == 2 - 1
    assert score({"minutes": 90, "goals_conceded": 4}, "DEF", RULES) == 2 - 2
    assert score({"minutes": 90, "goals_conceded": 4}, "MID", RULES) == 2


def test_saves_floor_per_three():
    assert score({"minutes": 90, "saves": 5}, "GKP", RULES) == 2 + 1
    assert score({"minutes": 90, "saves": 6}, "GKP", RULES) == 2 + 2


def test_defensive_contribution_thresholds():
    assert score({"minutes": 90, "defensive_contribution": 10},
                 "DEF", RULES) == 4
    assert score({"minutes": 90, "defensive_contribution": 11},
                 "MID", RULES) == 2
    assert score({"minutes": 90, "defensive_contribution": 12},
                 "MID", RULES) == 4
    assert score({"minutes": 90, "defensive_contribution": 15},
                 "GKP", RULES) == 2
