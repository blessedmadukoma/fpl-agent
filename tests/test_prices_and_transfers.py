from fpl.optimise.prices import selling_price
from fpl.team_state import free_transfers


def test_selling_price_keeps_half_the_rise_rounded_down():
    assert selling_price(purchase_price=60, now_cost=63) == 61
    assert selling_price(purchase_price=60, now_cost=64) == 62


def test_selling_price_takes_the_whole_fall():
    assert selling_price(purchase_price=60, now_cost=58) == 58
    assert selling_price(purchase_price=60, now_cost=60) == 60


def _weeks(*transfers):
    return [{"event": gw, "event_transfers": n} for gw, n in enumerate(transfers, start=1)]


def test_free_transfers_roll_over_and_cap_at_five():
    assert free_transfers(_weeks(0, 0, 0), {},
                          started_event=1, max_free=5) == 3
    assert free_transfers(_weeks(0, 0, 0, 0, 0, 0, 0, 0),
                          {}, started_event=1, max_free=5) == 5


def test_a_hit_leaves_one_free_transfer():
    assert free_transfers(_weeks(0, 3), {}, started_event=1, max_free=5) == 1


def test_wildcard_week_keeps_saved_transfers_without_the_plus_one():
    # GW2 +0 -> 2 for GW3; wildcard in GW3 keeps 2 for GW4
    assert free_transfers(
        _weeks(0, 0, 9), {3: "wildcard"}, started_event=1, max_free=5) == 2


def test_the_example_team():
    # Entry 1234567 in 2026/27: no transfers in GW2-3, two in GW4, two in GW5 -> 1 for GW6
    assert free_transfers(_weeks(0, 0, 0, 2, 2), {},
                          started_event=1, max_free=5) == 1
