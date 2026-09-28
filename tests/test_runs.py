import json

import duckdb
import pandas as pd

from fpl.runs import settle


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
