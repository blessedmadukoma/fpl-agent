import json
from types import SimpleNamespace

import duckdb
import pandas as pd

from fpl.optimise.chip_decision import ChipDecision
from fpl.runs import save_run, settle


def test_settle_fills_realised_points_for_both_plans():
    con = duckdb.connect()
    con.execute(
        "create table events as select '2026-27' as season, 6 as gw, true as finished")
    points = pd.DataFrame({"season": "2026-27", "gw": 6,
                          "element": [1, 2, 3], "total_points": [2.0, 6.0, 9.0]})
    con.register("p", points)
    con.execute("create table player_gw as select * from p")
    run = pd.DataFrame([{
        "run_id": "r1", "season": "2026-27", "gw": 6,
        "xi": json.dumps([1, 2]), "captain": 2, "hold_xi": json.dumps([1, 3]), "hold_captain": 3,
        "realised_points": None, "hold_realised_points": None,
    }]).astype({"realised_points": "float", "hold_realised_points": "float"})
    con.register("r", run)
    con.execute("create table runs as select * from r")

    assert settle(con) == 1
    realised, hold = con.execute(
        "select realised_points, hold_realised_points from runs").fetchone()
    assert realised == 2 + 6 + 6      # captain counts twice
    assert hold == 2 + 9 + 9


def test_chip_advice_is_saved_separately_without_changing_existing_run_schema():
    with duckdb.connect(":memory:") as con:
        first = SimpleNamespace(
            buy=[], sell=[], xi=[1, 2], captain=2, expected_points=6.0,
        )
        result = SimpleNamespace(
            ctx=SimpleNamespace(season="2026-27", gw=9),
            team=SimpleNamespace(entry_id=1),
            chosen=SimpleNamespace(gws=[first]), hold=SimpleNamespace(gws=[first]),
            gain=0.0, threshold=2.0, make_transfers=False,
            ep=pd.DataFrame({9: [2.0, 2.0]}, index=[1, 2]),
            chip_decision=None,
        )
        original_run = save_run(con, result, "full")
        result.chip_decision = ChipDecision(
            "save", None, "Better future opportunity.", [9, 10], [], [],
        )
        new_run = save_run(con, result, "full")
        assert con.execute("select count(*) from runs").fetchone()[0] == 2
        stored = con.execute("select run_id, decision from run_chip_advice").fetchall()
        assert len(stored) == 1 and stored[0][0] == new_run
        assert json.loads(stored[0][1])["action"] == "save"
        assert con.execute(
            "select expected_points from runs where run_id in (?, ?)",
            [original_run, new_run],
        ).fetchall() == [(6.0,), (6.0,)]
