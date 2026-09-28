"""The solver on a small made-up universe where the right answer is obvious."""

import pandas as pd

from fpl.optimise.solver import SolverSettings, optimise
from fpl.team_state import SquadPlayer, TeamState

QUOTAS = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}


def _universe():
    """15 owned players on 15 different clubs, plus 4 cheap stars from one club (club 99)."""
    rows, element = [], 1
    for position, count in QUOTAS.items():
        for _ in range(count):
            rows.append({"element": element, "position": position,
                        "team": element, "now_cost": 50})
            element += 1
    for position in ["MID", "MID", "FWD", "DEF"]:
        rows.append({"element": element, "position": position,
                    "team": 99, "now_cost": 50})
        element += 1
    players = pd.DataFrame(rows)
    ep = pd.DataFrame({6: 2.0, 7: 2.0}, index=players.element)
    ep.loc[16:19] = 8.0  # the four stars
    team = TeamState(0, "test", 5, tuple(SquadPlayer(e, 50, 50) for e in range(1, 16)), bank=0,
                     free_transfers=1, chips_available=(), chips_used=())
    return players, ep, team


def _check_squad(plan, players):
    info = players.set_index("element")
    for gw in plan.gws:
        squad = gw.xi + gw.bench
        assert len(set(squad)) == 15 and len(gw.xi) == 11
        assert info.loc[squad].position.value_counts().to_dict() == QUOTAS
        assert info.loc[squad].team.value_counts().max() <= 3
        assert gw.captain in gw.xi and gw.vice in gw.xi and gw.captain != gw.vice


def test_uses_the_free_transfer_on_a_star():
    players, ep, team = _universe()
    plan = optimise(ep, players, team)
    _check_squad(plan, players)
    assert len(plan.gws[0].buy) == 1 and plan.gws[0].buy[0] in range(16, 20)
    assert plan.gws[0].hits == 0


def test_club_limit_stops_a_fourth_star():
    players, ep, team = _universe()
    team = TeamState(**{**team.__dict__, "free_transfers": 5})
    plan = optimise(ep, players, team)
    _check_squad(plan, players)
    owned_stars = [p for p in plan.gws[-1].xi + plan.gws[-1].bench if p >= 16]
    assert len(owned_stars) == 3


def test_rolling_gives_two_free_transfers_next_week():
    players, ep, team = _universe()
    plan = optimise(ep, players, team, SolverSettings(hold_first_gw=True))
    assert plan.gws[0].buy == []
    assert plan.gws[1].free_transfers == 2
    assert len(plan.gws[1].buy) == 2
