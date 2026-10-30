"""Chip timing, inventory and legality on small, explicit value tables."""

import pandas as pd
import pytest

from fpl.optimise.chip_decision import assess_chips, chip_projection_gws, decide_chips
from fpl.report import print_chip_decision
from fpl.team_state import TeamState


def team(chips=(), expiry=10, used=()):
    return TeamState(1, "Test", 8, (), 0, 0,
                     tuple(f"{chip} (until GW{expiry})" for chip in chips), used)


def values(gws=(9, 10), tc=(0, 0), bb=(0, 0), fh=(0, 0)):
    return pd.DataFrame({"gw": gws, "triple_captain": tc,
                         "bench_boost": bb, "free_hit": fh})


def test_no_available_chips_and_wildcard_only_are_distinct():
    empty = decide_chips(pd.DataFrame(), team(), 9)
    assert empty.action == "none_available"
    wildcard = decide_chips(pd.DataFrame(), team(("wildcard",)), 9)
    assert wildcard.action == "review_required"
    assert wildcard.chip is None
    assert next(option for option in wildcard.options if option.available).gain_now is None


def test_future_opportunities_mean_save_available_chips():
    result = decide_chips(
        values((9, 10, 11), (2, 8, 1), (3, 2, 12), (100, 0, 0)),
        team(("3xc", "bboost", "wildcard"), expiry=11), 9,
    )
    assert result.action == "save"
    options = {option.chip: option for option in result.options}
    assert options["3xc"].planned_gw == 10
    assert options["bboost"].planned_gw == 11
    assert not options["freehit"].available
    assert "Wildcard remains unassessed" in result.reason


def test_one_chip_per_gw_uses_best_total_instead_of_greedy_gain():
    result = decide_chips(
        values(tc=(6, 0), bb=(10, 9)), team(("3xc", "bboost")), 9,
    )
    assert result.action == "use"
    assert result.chip == "3xc"
    planned = {option.chip: option.planned_gw for option in result.options if option.available}
    assert planned == {"3xc": 9, "bboost": 10}


def test_expiry_prevents_deferring_to_a_higher_value_after_the_window():
    result = decide_chips(values(tc=(5, 100)), team(("3xc",), expiry=9), 9)
    assert result.action == "use"
    assert result.options[0].planned_gw == 9
    assert result.options[0].planned_gain == 5


def test_free_hit_now_requires_review_of_the_transfer_plan():
    result = decide_chips(values(fh=(12, 1)), team(("freehit",)), 9)
    assert result.action == "review_required"
    assert result.chip == "freehit"
    assert "reversion" in result.reason


def test_free_hit_cannot_be_used_in_consecutive_half_season_windows():
    result = decide_chips(
        values((20, 21), fh=(100, 3)),
        team(("freehit",), expiry=21, used=("freehit (GW19)",)), 20,
    )
    option = next(option for option in result.options if option.available)
    assert result.action == "save"
    assert option.gain_now is None
    assert option.planned_gw == 21


def test_zero_values_do_not_trigger_a_chip_or_claim_a_future_gain():
    result = decide_chips(values(), team(("3xc", "bboost")), 9)
    assert result.action == "save"
    assert result.chip is None
    assert "No positive gain" in result.reason
    assert all(option.planned_gw is None for option in result.options)


@pytest.mark.parametrize("frame", [
    values((9,), (2,), (0,), (0,)),
    values((9, 11), (2, 4), (0, 0), (0, 0)),
])
def test_incomplete_projection_window_is_rejected(frame):
    with pytest.raises(ValueError, match="expiry"):
        decide_chips(frame, team(("3xc",), expiry=11), 9)


def test_nonfinite_chip_values_are_rejected():
    with pytest.raises(ValueError, match="finite"):
        decide_chips(values(tc=(float("nan"), 2)), team(("3xc",)), 9)


def test_short_prepared_projections_request_review_without_breaking_the_plan():
    decision = assess_chips(pd.DataFrame({9: [2.0]}), pd.DataFrame(), team(("3xc",)))
    assert decision.action == "review_required"
    assert decision.chip is None
    assert "through expiry" in decision.reason


def test_projection_range_uses_inventory_expiry_and_skips_unvalued_chips():
    assert chip_projection_gws(team(("3xc", "wildcard"), expiry=19), 9) == list(range(9, 20))
    assert chip_projection_gws(team(("bboost",), expiry=38), 35) == [35, 36, 37, 38]
    assert chip_projection_gws(team(("wildcard",), expiry=19), 9) == []
    assert chip_projection_gws(team(("3xc",), expiry=19), 20) == []


def test_report_exposes_decision_timing_expiry_and_unassessed_wildcard(capsys):
    result = decide_chips(
        values(tc=(3, 7)), team(("3xc", "wildcard")), 9,
    )
    print_chip_decision(result)
    output = capsys.readouterr().out
    assert "Chip decision: SAVE" in output
    assert "now +3.00 EP; planned GW10, +7.00 EP; expires GW10" in output
    assert "Wildcard" in output and "not valued" in output
    assert "separate" in output
