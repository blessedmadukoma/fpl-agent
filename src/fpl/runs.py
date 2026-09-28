"""Record every recommendation, then settle it after the GW with the real points.

Two plans are stored for each run: the one recommended and the "roll the transfer" plan.
After the GW, both get their realised points, so you can see whether acting helped.
Realised points ignore autosubs and chips: they compare decisions, not your FPL total.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pandas as pd

from fpl.storage import query, replace_rows, table_exists


def save_run(con, result, model: str) -> str:
    run_id = uuid.uuid4().hex[:12]
    chosen, hold = result.chosen.gws[0], result.hold.gws[0]
    row = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc),
        "season": result.ctx.season,
        "gw": result.ctx.gw,
        "entry_id": result.team.entry_id,
        "model": model,
        "gain": result.gain,
        "threshold": result.threshold,
        "made_transfers": result.make_transfers,
        "buy": json.dumps(chosen.buy),
        "sell": json.dumps(chosen.sell),
        "xi": json.dumps(chosen.xi),
        "captain": chosen.captain,
        "expected_points": chosen.expected_points,
        "hold_xi": json.dumps(hold.xi),
        "hold_captain": hold.captain,
        "hold_expected_points": hold.expected_points,
        "realised_points": None,
        "hold_realised_points": None,
    }
    replace_rows(con, "runs", pd.DataFrame([row]).astype({"realised_points": "float", "hold_realised_points": "float"}),
                 run_id=run_id)
    projections = result.ep[[result.ctx.gw]].rename(
        columns={result.ctx.gw: "ep"}).rename_axis("element").reset_index()
    replace_rows(con, "run_projections", projections.assign(
        run_id=run_id, gw=result.ctx.gw), run_id=run_id)
    return run_id


def settle(con) -> int:
    """Fill in realised points for every run whose GW has finished. Returns runs updated."""
    if not table_exists(con, "runs"):
        return 0
    open_runs = query(con, """
        select r.* from runs r join events e on e.season = r.season and e.gw = r.gw
        where e.finished and r.realised_points is null""")
    for run in open_runs.itertuples():
        points = query(con, "select element, total_points from player_gw where season = ? and gw = ?",
                       [run.season, run.gw]).set_index("element").total_points

        def realised(xi, captain): return float(points.reindex(
            json.loads(xi)).fillna(0).sum() + points.get(captain, 0))
        con.execute("update runs set realised_points = ?, hold_realised_points = ? where run_id = ?",
                    [realised(run.xi, run.captain), realised(run.hold_xi, run.hold_captain), run.run_id])
    return len(open_runs)


def run_history(con) -> pd.DataFrame:
    if not table_exists(con, "runs"):
        return pd.DataFrame()
    return query(con, """
        select gw, created_at, model, made_transfers, round(gain, 2) as gain,
               round(expected_points, 1) as expected, realised_points as realised,
               round(hold_expected_points, 1) as hold_expected, hold_realised_points as hold_realised
        from runs order by created_at""")
