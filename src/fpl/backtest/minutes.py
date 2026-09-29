"""Score the minutes model against simple lookup tables, on GWs it was not trained on."""

from __future__ import annotations

import pandas as pd

from fpl.backtest.metrics import log_loss
from fpl.projections import minutes as mm


def minutes_backtest(con, season: str, split_gw: int = 20, last_gw: int = 38) -> pd.DataFrame:
    train_gws = [(season, g) for g in range(2, split_gw)]
    test_gws = [(season, g) for g in range(split_gw, last_gw + 1)]
    train = mm.training_rows(con, train_gws)
    test = mm.training_rows(con, test_gws)
    model = mm.train(con, train_gws)
    predicted = model.predict(test)

    def lookup(keys: list[str]) -> pd.Series:
        rates = train.groupby(keys).played_60.mean()
        fallback = train.groupby("started_last").played_60.mean()
        index = pd.MultiIndex.from_frame(
            test[keys]) if len(keys) > 1 else test[keys[0]]
        values = rates.reindex(index).to_numpy()
        return pd.Series(values, index=test.index).fillna(test.started_last.map(fallback))

    candidates = [
        ("constant rate", "60+ minutes",
         pd.Series(train.played_60.mean(), index=test.index), test.played_60),
        ("started last GW", "60+ minutes",
         lookup(["started_last"]), test.played_60),
        ("started last GW x flag", "60+ minutes",
         lookup(["started_last", "flag"]), test.played_60),
        ("minutes model", "60+ minutes", predicted.p_60, test.played_60),
        ("minutes model", "started", predicted.p_start, test.started),
    ]
    return pd.DataFrame(
        [{"model": name, "target": target, "log_loss": log_loss(
            p, y)} for name, target, p, y in candidates]
    ).assign(test_rows=len(test))
