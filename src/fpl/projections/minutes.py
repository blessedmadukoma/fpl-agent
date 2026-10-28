"""Minutes model: P(start), P(60+ minutes), P(any minutes) for each player in the next GW.

Logistic regressions on a few features that only use data from before the deadline:
recent starts and minutes, the season start rate, the FPL availability flag, the `news`
text ("Expected back 10 Oct") and position. See 01-reference.md H.3.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder

from fpl.context import GwContext, load_context
from fpl.storage import query

logger = logging.getLogger(__name__)

NUMERIC = ["started_last", "starts_last4",
           "minutes_last4", "season_start_rate", "games"]
CATEGORICAL = ["flag", "position", "news_kind"]
TARGETS = {"p_start": "started", "p_60": "played_60", "p_play": "played"}

EXPECTED_BACK = re.compile(r"Expected back (\d{1,2}) ([A-Z][a-z]{2})")


def flag_category(status: str, chance) -> str:
    """FPL status + chance of playing as one label (a flag is not a probability)."""
    if status in {"i", "s", "n", "u"} or chance == 0:
        return "out"
    if pd.isna(chance):
        return "none"
    return f"{status}{int(chance)}"


def news_kind(news: str, deadline: pd.Timestamp) -> str:
    """Classify the `news` text with a regular expression. No LLM needed for this part."""
    if not news:
        return "none"
    match = EXPECTED_BACK.search(news)
    if match:
        day, month = match.groups()
        back = pd.Timestamp(f"{day} {month} {deadline.year}", tz="UTC")
        # e.g. "Expected back 3 Jan" said in December
        if back < deadline - pd.Timedelta(days=180):
            back += pd.DateOffset(years=1)
        return "back_by_deadline" if back <= deadline + pd.Timedelta(days=2) else "back_later"
    if "Unknown return date" in news:
        return "unknown_return"
    if "Suspended" in news:
        return "suspended"
    return "other"


def features(ctx: GwContext) -> pd.DataFrame:
    """One row per player in ctx.state, built only from data before ctx.gw."""
    history = ctx.history.sort_values("gw")
    started = (history.starts > 0).astype(float)
    per_player = history.assign(started=started).groupby("element")
    recent = history.assign(started=started).groupby(
        "element").tail(4).groupby("element")
    table = pd.DataFrame(
        {
            "started_last": per_player.started.last(),
            "starts_last4": recent.started.mean(),
            "minutes_last4": recent.minutes.mean() / 90,
            "season_start_rate": per_player.started.mean(),
            "games": per_player.size(),
        }
    )
    state = ctx.state.set_index("element")
    table = table.reindex(state.index).fillna(0.0)
    table["flag"] = [flag_category(s, c)
                     for s, c in zip(state.status, state.chance)]
    table["position"] = state.position
    table["news_kind"] = [news_kind(n, ctx.deadline)
                          for n in state.news.fillna("")]
    return table


def outcomes(con, season: str, gw: int) -> pd.DataFrame:
    rows = query(
        con, "select element, starts, minutes from player_gw where season = ? and gw = ?", [season, gw])
    flags = {"started": rows.starts > 0,
             "played_60": rows.minutes >= 60, "played": rows.minutes > 0}
    return pd.DataFrame({k: v.to_numpy(dtype=int) for k, v in flags.items()}, index=rows.element.to_numpy())


def training_rows(con, season_gws: list[tuple[str, int]]) -> pd.DataFrame:
    frames = []
    for season, gw in season_gws:
        ctx = load_context(con, season, gw)
        frames.append(features(ctx).join(outcomes(con, season, gw),
                      how="inner").assign(season=season, gw=gw))
    return pd.concat(frames)


@dataclass
class MinutesModel:
    models: dict
    minutes_if_60: float    # mean minutes when a player plays 60+
    minutes_if_short: float  # mean minutes when a player plays 1-59

    @classmethod
    def fit(cls, rows: pd.DataFrame, minutes: pd.Series) -> "MinutesModel":
        models = {}
        for name, target in TARGETS.items():
            encoder = ColumnTransformer(
                [("categories", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL)], remainder="passthrough"
            )
            model = make_pipeline(
                encoder, LogisticRegression(C=1.0, max_iter=2000))
            models[name] = model.fit(rows[CATEGORICAL + NUMERIC], rows[target])
        long_ = minutes[minutes >= 60]
        short = minutes[(minutes > 0) & (minutes < 60)]
        return cls(models, float(long_.clip(upper=90).mean()), float(short.mean()))

    def predict(self, table: pd.DataFrame) -> pd.DataFrame:
        x = table[CATEGORICAL + NUMERIC]
        out = pd.DataFrame({name: m.predict_proba(
            x)[:, 1] for name, m in self.models.items()}, index=table.index)
        out["p_play"] = np.maximum(out.p_play, out.p_60)
        out["p_start"] = np.minimum(out.p_start, out.p_play)
        out["p_short"] = out.p_play - out.p_60  # 1-59 minutes
        out["e_minutes"] = out.p_60 * self.minutes_if_60 + \
            out.p_short * self.minutes_if_short
        return out


def train(con, season_gws: list[tuple[str, int]]) -> MinutesModel:
    rows = training_rows(con, season_gws)
    minutes = pd.concat(
        query(con, "select minutes from player_gw where season = ? and gw = ?", [s, g]).minutes for s, g in season_gws
    )
    return MinutesModel.fit(rows, minutes)


def training_gws(con, season: str, before_gw: int, previous_season: str | None) -> list[tuple[str, int]]:
    """Available training GWs, excluding this season's target GW and later.

    Require a deadline and saved state with matching player results. A live
    update can recover past results, but not a missing historical state.
    """
    gws = [(season, g) for g in range(2, before_gw)]
    if previous_season:
        done = query(con, "select distinct gw from state where season = ? and gw >= 2", [
                     previous_season]).gw
        gws = [(previous_season, int(g)) for g in sorted(done)] + gws

    available = query(con, """
        select distinct s.season, s.gw
        from state s
        join events e on e.season = s.season and e.gw = s.gw
        join player_gw p on p.season = s.season and p.gw = s.gw
                       and p.element = s.element
        where s.season in (?, ?) and s.gw >= 2
          and e.deadline is not null
    """, [season, previous_season])
    available_gws = set(available.itertuples(index=False, name=None))
    selected = [pair for pair in gws if pair in available_gws]
    skipped = [pair for pair in gws if pair not in available_gws]
    if skipped:
        logger.warning(
            "Skipping minutes-model training weeks with missing saved state, "
            "deadline or matching player results: %s",
            ", ".join(f"{s} GW{g}" for s, g in skipped),
        )
    if not selected:
        raise LookupError(
            "No usable minutes-model training gameweeks. "
            "Load historical saved state, deadlines and matching player results; "
            "a current update cannot recreate missing historical state."
        )
    return selected
