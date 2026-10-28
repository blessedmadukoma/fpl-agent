# FPL Agent 03 — Build, Part 2: better projections, chips and the GW6 deadline

Version 3, 26 September 2026. Part 2 continues from the end of Part 1, when all 15 tests pass and
`fpl recommend` works. It replaces the skeleton projection with a model built from components
(minutes, team strength, goals, assists, clean sheets, DefCon, bonus). The new model is used only
after it beats the skeleton in the backtest. The last step is the GW6 deadline runbook.

Continue with **03-agent-build-part3.md** for Step 13 onwards: freeze an evaluation snapshot, add a
read-only LLM layer, trace it, run fixed evaluations, add the news layer and close the remaining
model and deployment gaps.

The same conventions as Part 1 apply:

- Create each file exactly as shown.
- Paste `cli.py` blocks above `# --- Entry point`, and `report.py` blocks at the end.
- Run the command, compare with the expected output, then commit.

| Step | Adds                               | Tangible result                                               |
| ---- | ---------------------------------- | ------------------------------------------------------------- |
| 8    | bookmaker odds and a team model    | a clean-sheet table for the next 6 GWs; a Brier score to beat |
| 9    | a minutes model                    | log loss 0.250 against 0.285 for the best lookup table        |
| 10   | the full points model and the gate | a model that beats the skeleton on every gate number          |
| 11   | chip values up to GW19             | the best GW for each chip                                     |
| 12   | the GW6 deadline runbook           | exact commands and times                                      |

---

## Step 8 — Bookmaker odds and the team model

**Goal:** expected goals for and against every team in every fixture of the next GWs. The
numbers come from bookmaker odds where they exist, and from team ratings everywhere else. These
give clean-sheet probabilities, and an attack factor for goals and assists (§H.4).

`src/fpl/projections/goals.py`

```python
"""Goal-rate maths: bookmaker odds -> expected goals per team (λ), and Poisson helpers."""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

MAX_GOALS = 10


def remove_margin(odds: list[float]) -> np.ndarray:
    """Decimal odds -> probabilities that sum to 1 (proportional method)."""
    implied = 1 / np.asarray(odds, dtype=float)
    return implied / implied.sum()


def outcome_probabilities(lambda_home: float, lambda_away: float) -> tuple[float, float, float, float]:
    """P(home win), P(draw), P(away win), P(over 2.5 goals) under independent Poisson goals."""
    goals = np.arange(MAX_GOALS + 1)
    grid = np.outer(poisson.pmf(goals, lambda_home), poisson.pmf(goals, lambda_away))
    total = np.add.outer(goals, goals)
    return float(np.tril(grid, -1).sum()), float(np.trace(grid)), float(np.triu(grid, 1).sum()), float(grid[total >= 3].sum())


def rates_from_odds(home: float, draw: float, away: float, over25: float, under25: float) -> tuple[float, float]:
    """Find (λ_home, λ_away) whose Poisson probabilities best match the market."""
    target = np.append(remove_margin([home, draw, away]), remove_margin([over25, under25])[0])

    def loss(log_rates: np.ndarray) -> float:
        return float(np.sum((np.array(outcome_probabilities(*np.exp(log_rates))) - target) ** 2))

    result = minimize(loss, np.log([1.4, 1.1]), method="Nelder-Mead", options={"xatol": 1e-5, "fatol": 1e-10})
    lambda_home, lambda_away = np.exp(result.x)
    return float(lambda_home), float(lambda_away)


def expected_floor(rate: np.ndarray | float, per: int) -> np.ndarray:
    """E[floor(N / per)] for N ~ Poisson(rate). Used for goals conceded (per 2) and saves (per 3)."""
    k = np.arange(MAX_GOALS * 3 + 1)
    pmf = poisson.pmf(k[:, None], np.atleast_1d(rate)[None, :])
    return (pmf * (k // per)[:, None]).sum(axis=0)
```

`rates_from_odds` finds the two Poisson rates that reproduce the market's home, draw, away and
over-2.5 probabilities. `expected_floor` computes the exact goals-conceded and saves terms,
E[floor(N/2)] and E[floor(N/3)].

`src/fpl/ingest/odds.py`

```python
"""Bookmaker odds from football-data.co.uk, turned into expected goals per team per fixture.

- mmz4281/{yyyy}/E0.csv: every Premier League match of a season, with pre-match odds.
- fixtures.csv: the coming round's matches. Weekend odds appear on Friday afternoon.
We use the market average (Avg*) columns. See 01-reference.md H.4.
"""

from __future__ import annotations

import pandas as pd

from fpl.config import CURRENT_SEASON, Settings
from fpl.ingest.download import download
from fpl.projections.goals import rates_from_odds
from fpl.storage import query, replace_rows

SEASON_URL = "https://football-data.co.uk/mmz4281/{code}/E0.csv"
UPCOMING_URL = "https://football-data.co.uk/fixtures.csv"
ODDS_COLUMNS = ["AvgH", "AvgD", "AvgA", "Avg>2.5", "Avg<2.5"]

# football-data club name -> FPL short name (stable across seasons)
CLUB_CODES = {
    "Arsenal": "ARS", "Aston Villa": "AVL", "Bournemouth": "BOU", "Brentford": "BRE", "Brighton": "BHA",
    "Burnley": "BUR", "Chelsea": "CHE", "Coventry": "COV", "Crystal Palace": "CRY", "Everton": "EVE",
    "Fulham": "FUL", "Hull": "HUL", "Ipswich": "IPS", "Leeds": "LEE", "Leicester": "LEI", "Liverpool": "LIV",
    "Man City": "MCI", "Man United": "MUN", "Newcastle": "NEW", "Nott'm Forest": "NFO", "Southampton": "SOU",
    "Sunderland": "SUN", "Tottenham": "TOT", "West Ham": "WHU", "Wolves": "WOL",
}


def _read(path, source: str) -> pd.DataFrame:
    """Keep only the columns we use (the files have over 100)."""
    df = pd.read_csv(path, encoding="utf-8-sig")
    if "Div" in df.columns:
        df = df[df.Div == "E0"]
    return df[["HomeTeam", "AwayTeam", *ODDS_COLUMNS]].assign(source=source)


def load_odds(settings: Settings, con, season: str) -> dict:
    """Write the `odds` table for one season: one row per fixture with odds-implied λ."""
    code = season[2:4] + season[5:7]  # "2025-26" -> "2526"
    folder = settings.cache_dir / "football-data"
    current = season == CURRENT_SEASON
    frames = [_read(download(SEASON_URL.format(code=code), folder / f"E0_{code}.csv", refresh=current), "result")]
    if current:
        frames.append(_read(download(UPCOMING_URL, folder / "fixtures.csv", refresh=True), "upcoming"))
    raw = pd.concat(frames, ignore_index=True).dropna(subset=ODDS_COLUMNS)

    teams = query(con, "select team_id, short_name from teams where season = ?", [season])
    team_id = dict(zip(teams.short_name, teams.team_id))
    raw["team_h"] = raw.HomeTeam.map(CLUB_CODES).map(team_id)
    raw["team_a"] = raw.AwayTeam.map(CLUB_CODES).map(team_id)
    unmapped = raw[raw.team_h.isna() | raw.team_a.isna()]
    if not unmapped.empty:
        names = sorted(set(unmapped.HomeTeam) | set(unmapped.AwayTeam))
        raise ValueError(f"Add these clubs to CLUB_CODES: {names}")

    fixtures = query(con, "select fixture_id, gw, team_h, team_a from fixtures where season = ?", [season])
    raw = raw.astype({"team_h": int, "team_a": int}).merge(fixtures, on=["team_h", "team_a"])
    raw = raw.sort_values("source").drop_duplicates("fixture_id", keep="first")  # "result" wins

    rates = [rates_from_odds(*row) for row in raw[ODDS_COLUMNS].itertuples(index=False)]
    odds = pd.DataFrame(
        {
            "season": season,
            "fixture_id": raw.fixture_id.to_numpy(),
            "gw": raw.gw.to_numpy(),
            "team_h": raw.team_h.to_numpy(),
            "team_a": raw.team_a.to_numpy(),
            "lambda_h": [r[0] for r in rates],
            "lambda_a": [r[1] for r in rates],
            "source": raw.source.to_numpy(),
        }
    )
    replace_rows(con, "odds", odds, season=season)
    return {"season": season, "fixtures": len(odds), "upcoming": int((odds.source == "upcoming").sum())}
```

`src/fpl/projections/teams.py`

```python
"""Expected goals for every fixture in the horizon, for clean sheets and opponent strength.

Two sources (01-reference.md H.4):
- the next GW: bookmaker odds, when football-data has them;
- later GWs, or when odds are missing: team ratings fitted to the odds-implied λ of past
  fixtures. Fitting to odds rather than to goals gives far less noisy ratings.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from fpl.context import GwContext
from fpl.storage import query

DECAY_PER_DAY = 0.005   # weight halves about every 140 days
RIDGE = 2.0             # pulls team ratings towards average when data is thin


@dataclass(frozen=True)
class TeamRatings:
    base: float
    home: float
    attack: dict[int, float]
    defence: dict[int, float]

    def rates(self, team_h: int, team_a: int) -> tuple[float, float]:
        a, d = self.attack, self.defence
        lambda_h = np.exp(self.base + self.home + a.get(team_h, 0.0) - d.get(team_a, 0.0))
        lambda_a = np.exp(self.base + a.get(team_a, 0.0) - d.get(team_h, 0.0))
        return float(lambda_h), float(lambda_a)

    def average_rate(self, team: int) -> float:
        """λ against an average opponent, with half the home advantage."""
        return float(np.exp(self.base + self.home / 2 + self.attack.get(team, 0.0)))


def fit_ratings(matches: pd.DataFrame, teams: list[int], ridge: float = RIDGE) -> TeamRatings:
    """Weighted ridge regression of log λ on attack, defence and home advantage.

    `matches` has team_h, team_a, lambda_h, lambda_a and weight.
    """
    index = {team: i for i, team in enumerate(teams)}
    n = len(teams)
    rows, targets, weights = [], [], []
    for m in matches.itertuples():
        for attacker, defender, is_home, rate in [(m.team_h, m.team_a, 1, m.lambda_h), (m.team_a, m.team_h, 0, m.lambda_a)]:
            row = np.zeros(2 + 2 * n)
            row[0], row[1] = 1.0, is_home
            row[2 + index[attacker]] = 1.0
            row[2 + n + index[defender]] = -1.0
            rows.append(row)
            targets.append(np.log(rate))
            weights.append(m.weight)
    x, y, w = np.array(rows), np.array(targets), np.sqrt(np.array(weights))
    penalty = np.hstack([np.zeros((2 * n, 2)), np.sqrt(ridge) * np.eye(2 * n)])
    design = np.vstack([x * w[:, None], penalty])
    response = np.concatenate([y * w, np.zeros(2 * n)])
    coef, *_ = np.linalg.lstsq(design, response, rcond=None)
    attack = {t: coef[2 + i] for t, i in index.items()}
    defence = {t: coef[2 + n + i] for t, i in index.items()}
    return TeamRatings(base=coef[0], home=coef[1], attack=attack, defence=defence)


def fixture_rates(con, ctx: GwContext, gws: list[int]) -> pd.DataFrame:
    """λ for every fixture of `gws`: odds for ctx.gw where available, ratings otherwise."""
    odds = query(con, "select * from odds where season = ? and gw <= ?", [ctx.season, ctx.gw])
    ratings = ratings_at(ctx, odds)
    upcoming = ctx.fixtures[ctx.fixtures.gw.isin(gws)][["fixture_id", "gw", "team_h", "team_a"]].copy()
    rated = [ratings.rates(h, a) for h, a in zip(upcoming.team_h, upcoming.team_a)]
    upcoming["lambda_h"] = [r[0] for r in rated]
    upcoming["lambda_a"] = [r[1] for r in rated]
    upcoming["source"] = "ratings"

    market = odds[odds.gw == ctx.gw].set_index("fixture_id")
    has_odds = upcoming.fixture_id.isin(market.index)
    for column in ("lambda_h", "lambda_a"):
        upcoming.loc[has_odds, column] = upcoming.loc[has_odds, "fixture_id"].map(market[column])
    upcoming.loc[has_odds, "source"] = "odds"
    upcoming["avg_h"] = upcoming.team_h.map(ratings.average_rate)
    upcoming["avg_a"] = upcoming.team_a.map(ratings.average_rate)
    return upcoming.reset_index(drop=True)


def ratings_at(ctx: GwContext, odds: pd.DataFrame) -> TeamRatings:
    """Ratings from the odds of fixtures played before ctx.gw (no leakage)."""
    past = odds[odds.gw < ctx.gw].merge(ctx.fixtures[["fixture_id", "kickoff"]], on="fixture_id")
    days_ago = (ctx.deadline - past.kickoff).dt.total_seconds() / 86400
    past = past.assign(weight=np.exp(-DECAY_PER_DAY * days_ago.to_numpy()))
    return fit_ratings(past, sorted(ctx.teams.team_id))


def team_view(rates: pd.DataFrame) -> pd.DataFrame:
    """One row per team per fixture: own λ (for attack) and opponent λ (for clean sheets)."""
    home = rates.rename(columns={"team_h": "team", "team_a": "opponent", "lambda_h": "lambda_for",
                                 "lambda_a": "lambda_against", "avg_h": "lambda_avg"})
    away = rates.rename(columns={"team_a": "team", "team_h": "opponent", "lambda_a": "lambda_for",
                                 "lambda_h": "lambda_against", "avg_a": "lambda_avg"})
    columns = ["fixture_id", "gw", "team", "opponent", "lambda_for", "lambda_against", "lambda_avg", "source"]
    view = pd.concat([home.assign(home=True), away.assign(home=False)])[columns + ["home"]]
    view["p_clean_sheet"] = np.exp(-view.lambda_against)
    view["attack_factor"] = view.lambda_for / view.lambda_avg
    return view.reset_index(drop=True)
```

The ratings are fitted to the **odds-implied λ** of past fixtures, not to goals scored. Odds are
much less noisy than goals, so five GWs of odds already give usable ratings. That matters for the
promoted clubs, which have no Premier League data from last season.

`src/fpl/backtest/teams.py`

```python
"""How good are the clean-sheet probabilities, by how far ahead they are made?"""

from __future__ import annotations

import pandas as pd

from fpl.backtest import metrics
from fpl.context import load_context
from fpl.projections.teams import fixture_rates, team_view


def clean_sheet_backtest(con, season: str, gws: range, horizon: int = 6) -> pd.DataFrame:
    rows = []
    for gw in gws:
        ctx = load_context(con, season, gw)
        ahead = [g for g in range(gw, gw + horizon) if g <= 38]
        view = team_view(fixture_rates(con, ctx, ahead))
        results = ctx.fixtures[["fixture_id", "goals_h", "goals_a", "team_h"]]
        view = view.merge(results, on="fixture_id")
        conceded = view.goals_a.where(view.team == view.team_h, view.goals_h)
        rows.append(view.assign(made_at=gw, clean_sheet=(conceded == 0).astype(float)))
    frame = pd.concat(rows, ignore_index=True)
    frame["gws_ahead"] = frame.gw - frame.made_at
    base_rate = frame.clean_sheet.mean()

    summary = []
    for (ahead, source), part in frame.groupby(["gws_ahead", "source"]):
        brier = metrics.brier(part.p_clean_sheet, part.clean_sheet)
        constant = metrics.brier(pd.Series(base_rate, index=part.index), part.clean_sheet)
        summary.append({"gws_ahead": ahead, "source": source, "n": len(part), "brier": brier,
                        "constant_rate_brier": constant, "skill": 1 - brier / constant})
    return pd.DataFrame(summary)
```

`tests/test_teams.py`

```python
import numpy as np
import pandas as pd

from fpl.projections.goals import expected_floor, outcome_probabilities, rates_from_odds
from fpl.projections.teams import fit_ratings


def test_odds_inversion_recovers_the_goal_rates():
    home, draw, away, over = outcome_probabilities(1.8, 0.9)
    lambda_h, lambda_a = rates_from_odds(1 / home, 1 / draw, 1 / away, 1 / over, 1 / (1 - over))
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
```

Add to `cli.py`, above `# --- Entry point`:

```python
# --- Step 8: odds and team model -----------------------------------------------------

@command("odds", "Download bookmaker odds and turn them into expected goals per fixture")
def cmd_odds(settings: Settings, args) -> None:
    from fpl.ingest.odds import load_odds

    with open_db(settings) as con:
        for season in (HISTORY_SEASON, CURRENT_SEASON):
            report.print_odds_load(load_odds(settings, con, season))


@command("fixtures", "Clean-sheet chance per team for the next GWs", arg("--gws", type=int, default=6))
def cmd_fixtures(settings: Settings, args) -> None:
    from fpl.context import load_context, next_gw
    from fpl.projections.teams import fixture_rates, team_view

    with open_db(settings) as con:
        ctx = load_context(con, CURRENT_SEASON, next_gw(con))
        view = team_view(fixture_rates(con, ctx, list(range(ctx.gw, ctx.gw + args.gws))))
    report.print_fixture_ticker(view, ctx)


@command("backtest-teams", "Score clean-sheet probabilities on a past season",
         arg("--season", default=HISTORY_SEASON))
def cmd_backtest_teams(settings: Settings, args) -> None:
    from fpl.backtest.teams import clean_sheet_backtest

    with open_db(settings) as con:
        print(report.table(clean_sheet_backtest(con, args.season, range(5, 39)), "{:.4f}"))
```

Add to the end of `report.py`:

```python
# --- Step 8: odds and team model -----------------------------------------------------

def print_odds_load(summary: dict) -> None:
    print(f"{summary['season']}: odds for {summary['fixtures']} fixtures ({summary['upcoming']} upcoming)")


def print_fixture_ticker(view: pd.DataFrame, ctx) -> None:
    """Clean-sheet % per team per GW; '*' marks bookmaker odds, no mark means team ratings."""
    short = ctx.teams.set_index("team_id").short_name
    view = view.assign(club=view.team.map(short), opp=view.opponent.map(short))
    cell = lambda r: f"{r.opp}({'H' if r.home else 'A'}) {100 * r.p_clean_sheet:3.0f}%{'*' if r.source == 'odds' else ' '}"
    grid = view.assign(cell=view.apply(cell, axis=1)).pivot_table(
        index="club", columns="gw", values="cell", aggfunc=" / ".join)
    grid["avg"] = view.groupby("club").p_clean_sheet.mean()
    grid = grid.sort_values("avg", ascending=False)
    grid["avg"] = (100 * grid["avg"]).map("{:.0f}%".format)
    print(f"Clean-sheet chance by GW from GW{ctx.gw} (* = bookmaker odds, otherwise team ratings)")
    print(grid.to_string())
```

**Run:**

```bash
python -m pytest -q tests/test_teams.py
fpl odds
fpl fixtures
fpl backtest-teams
```

**Expected output:**

```text
...                                                                      [100%]
3 passed in 0.95s
```

```text
2025-26: odds for 380 fixtures (0 upcoming)
2026-27: odds for 50 fixtures (0 upcoming)
```

```text
Clean-sheet chance by GW from GW6 (* = bookmaker odds, otherwise team ratings)
gw               6             7             8             9            10            11  avg
club
ARS   LEE(H)  41%   NFO(A)  35%   EVE(H)  42%   LIV(A)  26%   HUL(H)  50%   NEW(A)  32%   38%
MCI   LIV(A)  20%   IPS(H)  40%   AVL(A)  29%   BHA(H)  34%   NFO(A)  30%   FUL(H)  37%   32%
CHE   BOU(H)  30%   EVE(A)  26%   TOT(H)  30%   MUN(H)  25%   SUN(A)  32%   LEE(H)  32%   29%
TOT   MUN(A)  18%   COV(H)  37%   CHE(A)  18%   CRY(H)  33%   LEE(A)  24%   IPS(H)  34%   27%
MUN   TOT(H)  31%   LEE(A)  26%   BOU(H)  31%   CHE(A)  20%   AVL(H)  33%   LIV(A)  18%   26%
BRE   AVL(A)  23%   LIV(H)  20%   HUL(A)  32%   NFO(H)  30%   BHA(A)  22%   EVE(H)  30%   26%
LIV   MCI(H)  22%   BRE(A)  23%   BHA(H)  31%   ARS(H)  24%   CRY(A)  28%   MUN(H)  26%   26%
NEW   COV(A)  28%   AVL(H)  28%   CRY(A)  24%   EVE(H)  29%   FUL(A)  23%   ARS(H)  19%   25%
BHA   SUN(A)  29%   CRY(H)  31%   LIV(A)  15%   MCI(A)  14%   BRE(H)  26%   HUL(A)  31%   24%
AVL   BRE(H)  26%   NEW(A)  20%   MCI(H)  18%   FUL(H)  30%   MUN(A)  17%   SUN(H)  35%   24%
```

(The first 10 teams are shown. No GW6 cell has a `*` yet, because football-data publishes weekend
odds on the Friday afternoon before. Run `fpl odds` again on Friday 9 October.)

```text
 gws_ahead  source   n  brier constant_rate_brier  skill
         0    odds 680 0.1699              0.1815 0.0641
         1 ratings 660 0.1765              0.1837 0.0388
         2 ratings 640 0.1770              0.1867 0.0518
         3 ratings 620 0.1785              0.1875 0.0479
         4 ratings 600 0.1780              0.1867 0.0465
         5 ratings 580 0.1761              0.1875 0.0607
```

**How to read the backtest:**

- `gws_ahead 0` is the next GW, which uses odds: skill 6.4% over a constant clean-sheet rate.
- Ratings made 1–5 GWs ahead keep 4–6% skill.

Clean sheets are hard to predict, and single-digit skill is normal. These are the numbers your
future changes must beat.

**Checkpoint:** a clean-sheet table for every club, and a Brier score of 0.1699 for the next GW.
Commit.

---

## Step 9 — The minutes model

**Goal:** P(start), P(60+ minutes) and P(any minutes) for every player. Every other points
component scales with minutes (§C), so this model matters most.

`src/fpl/projections/minutes.py`

```python
"""Minutes model: P(start), P(60+ minutes), P(any minutes) for each player in the next GW.

Logistic regressions on a few features that only use data from before the deadline:
recent starts and minutes, the season start rate, the FPL availability flag, the `news`
text ("Expected back 10 Oct") and position. See 01-reference.md H.3.
"""

from __future__ import annotations

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

NUMERIC = ["started_last", "starts_last4", "minutes_last4", "season_start_rate", "games"]
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
        if back < deadline - pd.Timedelta(days=180):  # e.g. "Expected back 3 Jan" said in December
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
    recent = history.assign(started=started).groupby("element").tail(4).groupby("element")
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
    table["flag"] = [flag_category(s, c) for s, c in zip(state.status, state.chance)]
    table["position"] = state.position
    table["news_kind"] = [news_kind(n, ctx.deadline) for n in state.news.fillna("")]
    return table


def outcomes(con, season: str, gw: int) -> pd.DataFrame:
    rows = query(con, "select element, starts, minutes from player_gw where season = ? and gw = ?", [season, gw])
    flags = {"started": rows.starts > 0, "played_60": rows.minutes >= 60, "played": rows.minutes > 0}
    return pd.DataFrame({k: v.to_numpy(dtype=int) for k, v in flags.items()}, index=rows.element.to_numpy())


def training_rows(con, season_gws: list[tuple[str, int]]) -> pd.DataFrame:
    frames = []
    for season, gw in season_gws:
        ctx = load_context(con, season, gw)
        frames.append(features(ctx).join(outcomes(con, season, gw), how="inner").assign(season=season, gw=gw))
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
            model = make_pipeline(encoder, LogisticRegression(C=1.0, max_iter=2000))
            models[name] = model.fit(rows[CATEGORICAL + NUMERIC], rows[target])
        long_ = minutes[minutes >= 60]
        short = minutes[(minutes > 0) & (minutes < 60)]
        return cls(models, float(long_.clip(upper=90).mean()), float(short.mean()))

    def predict(self, table: pd.DataFrame) -> pd.DataFrame:
        x = table[CATEGORICAL + NUMERIC]
        out = pd.DataFrame({name: m.predict_proba(x)[:, 1] for name, m in self.models.items()}, index=table.index)
        out["p_play"] = np.maximum(out.p_play, out.p_60)
        out["p_start"] = np.minimum(out.p_start, out.p_play)
        out["p_short"] = out.p_play - out.p_60  # 1-59 minutes
        out["e_minutes"] = out.p_60 * self.minutes_if_60 + out.p_short * self.minutes_if_short
        return out


def train(con, season_gws: list[tuple[str, int]]) -> MinutesModel:
    rows = training_rows(con, season_gws)
    minutes = pd.concat(
        query(con, "select minutes from player_gw where season = ? and gw = ?", [s, g]).minutes for s, g in season_gws
    )
    return MinutesModel.fit(rows, minutes)


def training_gws(con, season: str, before_gw: int, previous_season: str | None) -> list[tuple[str, int]]:
    """Every GW before `before_gw` this season (from GW2), plus all of the previous season."""
    gws = [(season, g) for g in range(2, before_gw)]
    if previous_season:
        done = query(con, "select distinct gw from state where season = ? and gw >= 2", [previous_season]).gw
        gws = [(previous_season, int(g)) for g in sorted(done)] + gws
    return gws
```

The model is three logistic regressions on a few features, each built only from data before the
deadline.

- `flag_category` turns status and chance into one label, because a flag is not a probability
  (§H.3).
- `news_kind` reads "Expected back 10 Oct" with a regular expression. This part of reading the news
  needs no LLM.

`src/fpl/backtest/minutes.py`

```python
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
        index = pd.MultiIndex.from_frame(test[keys]) if len(keys) > 1 else test[keys[0]]
        values = rates.reindex(index).to_numpy()
        return pd.Series(values, index=test.index).fillna(test.started_last.map(fallback))

    candidates = [
        ("constant rate", "60+ minutes", pd.Series(train.played_60.mean(), index=test.index), test.played_60),
        ("started last GW", "60+ minutes", lookup(["started_last"]), test.played_60),
        ("started last GW x flag", "60+ minutes", lookup(["started_last", "flag"]), test.played_60),
        ("minutes model", "60+ minutes", predicted.p_60, test.played_60),
        ("minutes model", "started", predicted.p_start, test.started),
    ]
    return pd.DataFrame(
        [{"model": name, "target": target, "log_loss": log_loss(p, y)} for name, target, p, y in candidates]
    ).assign(test_rows=len(test))
```

`tests/test_minutes.py`

```python
import pandas as pd

from fpl.projections.minutes import flag_category, news_kind


def test_flag_categories():
    assert flag_category("a", None) == "none"
    assert flag_category("d", 75) == "d75"
    assert flag_category("i", 0) == "out"


def test_news_kind_reads_the_return_date():
    deadline = pd.Timestamp("2026-10-10 10:00", tz="UTC")
    assert news_kind("Hamstring injury - Expected back 10 Oct", deadline) == "back_by_deadline"
    assert news_kind("Knee injury - Expected back 7 Nov", deadline) == "back_later"
    assert news_kind("Knee injury - Unknown return date", deadline) == "unknown_return"
    assert news_kind("", deadline) == "none"
```

Add to `cli.py`, above `# --- Entry point`:

```python
# --- Step 9: minutes model -----------------------------------------------------------

@command("backtest-minutes", "Score the minutes model on GW20-38 after training on GW2-19",
         arg("--season", default=HISTORY_SEASON))
def cmd_backtest_minutes(settings: Settings, args) -> None:
    from fpl.backtest.minutes import minutes_backtest

    with open_db(settings) as con:
        print(report.table(minutes_backtest(con, args.season), "{:.4f}"))
```

**Run:**

```bash
python -m pytest -q tests/test_minutes.py
fpl backtest-minutes
```

**Expected output:**

```text
..                                                                       [100%]
2 passed in 1.09s
```

```text
                 model      target log_loss  test_rows
         constant rate 60+ minutes   0.5670      15117
       started last GW 60+ minutes   0.3394      15117
started last GW x flag 60+ minutes   0.2846      15117
         minutes model 60+ minutes   0.2502      15117
         minutes model     started   0.2387      15117
```

The model is trained on GW2–19 and tested on GW20–38, which it has not seen. Its log loss of
0.250 beats the best lookup table, 0.285. The gap is the value of the recent-minutes features and
of the news text.

**Checkpoint:** minutes-model log loss below 0.285. Commit.

---

## Step 10 — The full points model, and the gate

**Goal:** expected points from components (§H.1). The solver uses this model only if it beats the
shrunk blend in the backtest.

`src/fpl/projections/points.py`

```python
"""The full points model: expected points per player per fixture, built from components.

E[pts] = appearance + goals + assists + clean sheet − goals conceded + saves
         + defensive contribution + bonus − cards              (01-reference.md H.1)

Minutes come from the minutes model, goal rates from the team model, and each player's
per-90 rates are shrunk towards his position's average (H.2). Non-linear terms (clean
sheets, goals conceded, saves, DefCon) are computed per minutes scenario: 60+ or 1-59.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import nbinom

from fpl.context import GwContext
from fpl.checks import load_rules
from fpl.projections import minutes as minutes_model
from fpl.projections.goals import expected_floor
from fpl.projections.teams import fixture_rates, team_view
from fpl.scoring import DEFCON_THRESHOLD, Rules
from fpl.storage import query

PRIOR_90S = 6.0           # shrinkage strength k, in 90-minute matches (H.2)
PREVIOUS_SEASON_WEIGHT = 0.5  # last season's minutes count half
DEFCON_DISPERSION = 16.0  # negative-binomial φ, estimated per player on 2025/26 (close to Poisson)
RATE_STATS = ["expected_goals", "expected_assists", "defensive_contribution", "saves", "yellow_cards"]


@dataclass
class PointsModel:
    con: object
    minutes: minutes_model.MinutesModel
    previous: pd.DataFrame  # last season's totals per player code (may be empty)
    rules: Rules

    def project(self, ctx: GwContext, gws: list[int]) -> pd.DataFrame:
        """One row per player per fixture in `gws`, with every component and `ep`."""
        players = ctx.state.set_index("element")[["code", "team", "position"]]
        mins = self.minutes.predict(minutes_model.features(ctx))
        rates = shrunk_rates(ctx.history, players, self.previous)
        fixtures = team_view(fixture_rates(self.con, ctx, gws))

        df = players.join(mins).join(rates).reset_index().merge(fixtures, on="team")
        df["m60"], df["mshort"] = self.minutes.minutes_if_60, self.minutes.minutes_if_short
        return add_components(df, self.rules, fit_bonus(ctx.history))

    def __call__(self, ctx: GwContext) -> pd.Series:
        """Projector interface (one GW), so the backtest can score this model."""
        rows = self.project(ctx, [ctx.gw])
        return rows.groupby("element").ep.sum().reindex(ctx.state.element, fill_value=0.0).rename("ep")

    def horizon(self, ctx: GwContext, gws: list[int]) -> pd.DataFrame:
        rows = self.project(ctx, gws)
        table = rows.pivot_table(index="element", columns="gw", values="ep", aggfunc="sum")
        return table.reindex(index=ctx.state.element, columns=gws).fillna(0.0)


def build(con, season: str, first_gw: int, previous_season: str | None) -> PointsModel:
    """Train on data from before `first_gw` only, so the model can be backtested honestly."""
    gws = minutes_model.training_gws(con, season, first_gw, previous_season)
    return PointsModel(
        con=con,
        minutes=minutes_model.train(con, gws),
        previous=season_totals(con, previous_season) if previous_season else pd.DataFrame(),
        rules=load_rules(con, season),
    )


def season_totals(con, season: str) -> pd.DataFrame:
    """Minutes and rate stats per player code for a whole season."""
    sql = f"""
        select s.code, sum(p.minutes) as minutes, {", ".join(f"sum(p.{c}) as {c}" for c in RATE_STATS)}
        from player_gw p join (select distinct element, code from state where season = ?) s using (element)
        where p.season = ? group by s.code
    """
    return query(con, sql, [season, season]).set_index("code")


def shrunk_rates(history: pd.DataFrame, players: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    """Per-90 rates: (k·prior + events) / (k + 90s played). Prior = the position's average."""
    this_season = history.groupby("element")[["minutes", *RATE_STATS]].sum().reindex(players.index, fill_value=0.0)
    totals = this_season.copy()
    if not previous.empty:
        last = previous.reindex(players.code.to_numpy()).fillna(0.0).set_axis(players.index)
        totals = totals + PREVIOUS_SEASON_WEIGHT * last

    pooled = totals.join(players.position).groupby("position").sum()
    prior = pooled[RATE_STATS].div(pooled.minutes / 90, axis=0)
    per_player_prior = prior.reindex(players.position.to_numpy()).set_axis(players.index)

    nineties = totals.minutes / 90
    shrunk = (PRIOR_90S * per_player_prior + totals[RATE_STATS]).div(PRIOR_90S + nineties, axis=0)
    return shrunk.add_suffix("_90")


def fit_bonus(history: pd.DataFrame) -> pd.DataFrame:
    """Bonus per appearance ≈ a + b·goals + c·assists + d·clean sheet + e·(60+), per position.

    Fitted on this season only, because the BPS rules changed for 2026/27.
    """
    played = history[history.minutes > 0]
    coefficients = {}
    for position, rows in played.groupby("position"):
        x = np.column_stack([np.ones(len(rows)), rows.goals_scored, rows.assists, rows.clean_sheets,
                             (rows.minutes >= 60).astype(float)])
        coefficients[position], *_ = np.linalg.lstsq(x, rows.bonus.to_numpy(), rcond=None)
    return pd.DataFrame(coefficients, index=["base", "goal", "assist", "clean_sheet", "long_play"]).T


def add_components(df: pd.DataFrame, rules: Rules, bonus: pd.DataFrame) -> pd.DataFrame:
    pos = df.position
    points = lambda stat: pos.map(lambda p: rules.points(stat, p))
    per_90 = df.e_minutes / 90
    scenarios = [("p_60", "m60"), ("p_short", "mshort")]

    df["pts_appearance"] = 2 * df.p_60 + 1 * df.p_short
    df["e_goals"] = per_90 * df.expected_goals_90 * df.attack_factor
    df["e_assists"] = per_90 * df.expected_assists_90 * df.attack_factor
    df["pts_goals"] = df.e_goals * points("goals_scored")
    df["pts_assists"] = df.e_assists * points("assists")
    df["p_clean_sheet_60"] = df.p_60 * df.p_clean_sheet
    df["pts_clean_sheet"] = df.p_clean_sheet_60 * points("clean_sheets")

    conceded = sum(df[p] * expected_floor(df.lambda_against * df[m] / 90, 2) for p, m in scenarios)
    df["pts_conceded"] = conceded * points("goals_conceded")
    saves = sum(df[p] * expected_floor(df.saves_90 * df[m] / 90, 3) for p, m in scenarios)
    df["pts_saves"] = saves * points("saves") * (pos == "GKP")

    threshold = pos.map(DEFCON_THRESHOLD).to_numpy()
    df["p_defcon"] = sum(df[p] * _p_at_least(df.defensive_contribution_90 * df[m] / 90, threshold) for p, m in scenarios)
    df["pts_defcon"] = df.p_defcon * points("defensive_contribution")

    b = bonus.reindex(pos.to_numpy()).fillna(0.0).set_axis(df.index)
    df["pts_bonus"] = (b.base * (df.p_60 + df.p_short) + b.goal * df.e_goals + b.assist * df.e_assists
                       + b.clean_sheet * df.p_clean_sheet_60 + b.long_play * df.p_60).clip(lower=0)
    df["pts_cards"] = per_90 * df.yellow_cards_90 * points("yellow_cards")

    components = [c for c in df.columns if c.startswith("pts_")]
    df["ep"] = df[components].sum(axis=1)
    return df


def _p_at_least(mean: pd.Series, threshold: np.ndarray, dispersion: float = DEFCON_DISPERSION) -> np.ndarray:
    """P(X ≥ threshold) for a negative binomial with the given mean and dispersion."""
    mean = np.maximum(mean.to_numpy(dtype=float), 1e-9)
    p = dispersion / (dispersion + mean)
    return 1 - nbinom.cdf(np.minimum(threshold, 10**6) - 1, dispersion, p)
```

Read `add_components` from top to bottom: each line is one row of the scoring table in §D.

- **Clean sheets** use `p_60`, because the clean-sheet points need 60 minutes.
- **Goals conceded, saves and DefCon** are computed for each minutes scenario, then weighted by its
  probability (§G).
- **Every per-90 rate is shrunk** towards the position average (§H.2). For the current season, last
  season's minutes also count, at half weight.

Replace `src/fpl/projections/registry.py` with:

`src/fpl/projections/registry.py`

```python
"""Look up a projection model by name, so the CLI, backtest and solver can switch models.

Baselines need no training. The full model is trained on data from before `first_gw`,
so the same call works for a backtest (first_gw = 20) and for the live GW.
"""

from __future__ import annotations

from fpl.config import CURRENT_SEASON, HISTORY_SEASON
from fpl.projections.baseline import BASELINES, Projector

MODELS = [*BASELINES, "full"]


def build(name: str, con=None, season: str = CURRENT_SEASON, first_gw: int = 1) -> Projector:
    if name in BASELINES:
        return BASELINES[name]
    if name == "full":
        from fpl.projections.points import build as build_points

        previous = HISTORY_SEASON if season == CURRENT_SEASON else None
        return build_points(con, season, first_gw, previous)
    raise SystemExit(f"Unknown model '{name}'. Choose from: {', '.join(MODELS)}")
```

`build("full", con, season, first_gw)` trains the minutes model **only on GWs before
`first_gw`**. So `--from-gw 20` gives an honest test on unseen GWs, and the live run for GW6 uses
all of 2025/26 plus GW2–5.

Add to `cli.py`, above `# --- Entry point`:

```python
# --- Step 10: full points model ------------------------------------------------------

@command("projections", "Top players for the next GW with every points component",
         arg("--top", type=int, default=25), arg("--position", help="GKP, DEF, MID or FWD"))
def cmd_projections(settings: Settings, args) -> None:
    from fpl.context import load_context, next_gw
    from fpl.projections import registry

    with open_db(settings) as con:
        ctx = load_context(con, CURRENT_SEASON, next_gw(con))
        rows = registry.build("full", con, CURRENT_SEASON, first_gw=ctx.gw).project(ctx, [ctx.gw])
    report.print_projections(rows, ctx, args.top, args.position)
```

Add to the end of `report.py`:

```python
# --- Step 10: full points model ------------------------------------------------------

def print_projections(rows: pd.DataFrame, ctx, top: int, position: str | None) -> None:
    short = ctx.teams.set_index("team_id").short_name
    rows = rows.assign(player=rows.element.map(names(ctx).web_name), club=rows.team.map(short))
    if position:
        rows = rows[rows.position == position.upper()]
    columns = ["player", "club", "position", "p_start", "p_60", "pts_appearance", "pts_goals", "pts_assists",
               "pts_clean_sheet", "pts_defcon", "pts_bonus", "ep"]
    print(f"GW{ctx.gw} expected points, top {top}" + (f" {position.upper()}" if position else ""))
    print(table(rows.sort_values("ep", ascending=False)[columns].head(top)))
```

### 10.1 Run the gate

```bash
fpl backtest --model full --from-gw 20
fpl backtest --from-gw 20
```

**Expected output:**

```text
Model 'full', 2025-26 GW20-38
                                          pool     n rmse bias  rho
regular starters (3+ starts in previous 4 GWs)  3535 3.00 0.12 0.39
                  owned by 1%+ at the deadline  3587 2.93 0.01 0.58
                                   all players 15117 1.86 0.09 0.74
Top 15 per GW: projected 5.89, realised 4.80 (over-projection 1.09)
```

```text
Model 'shrunk_blend', 2025-26 GW20-38
                                          pool     n rmse  bias  rho
regular starters (3+ starts in previous 4 GWs)  3535 3.07  0.00 0.33
                  owned by 1%+ at the deadline  3587 3.00  0.01 0.54
                                   all players 15117 1.89 -0.02 0.77
Top 15 per GW: projected 5.87, realised 4.58 (over-projection 1.29)
```

| Gate test (GW20–38)                      | shrunk_blend | full     | Pass? |
| ---------------------------------------- | ------------ | -------- | ----- |
| Pool R RMSE (lower is better)            | 3.07         | **3.00** | yes   |
| Pool R ρ (higher is better)              | 0.33         | **0.39** | yes   |
| Pool O RMSE                              | 3.00         | **2.93** | yes   |
| Pool O ρ                                 | 0.54         | **0.58** | yes   |
| Top-15 over-projection (lower is better) | 1.29         | **1.09** | yes   |

The full model passes every test, so from now on use `--model full`. ρ over _all_ players is a
little lower (0.74 against 0.77). That pool is mostly players who never play, and the solver does
not choose between them, so it does not count in the gate.

**Known gap.** The backtest cannot test the model at GW6 of a season, because 2024/25 is not
loaded. For 2025/26 GW5–19 it would have had no last-season priors. Live at GW6 it does have
them. Part 3 Step 24 closes this gap.

### 10.2 Look at the projections

```bash
fpl projections --top 15
fpl projections --position DEF --top 8
```

```text
GW6 expected points, top 15
     player club position p_start p_60 pts_appearance pts_goals pts_assists pts_clean_sheet pts_defcon pts_bonus   ep
       Saka  ARS      MID    0.93 0.89           1.88      1.62        0.65            0.37       0.17      0.55 5.15
B.Fernandes  MUN      MID    0.94 0.91           1.90      1.48        0.82            0.28       0.22      0.54 5.12
     Mbeumo  MUN      MID    0.94 0.91           1.90      1.82        0.45            0.28       0.04      0.57 4.92
    Haaland  MCI      FWD    0.94 0.91           1.90      2.12        0.18            0.00       0.00      0.77 4.90
    Gabriel  ARS      DEF    0.95 0.92           1.90      0.51        0.16            1.53       0.59      0.31 4.62
     Palmer  CHE      MID    0.88 0.83           1.80      1.63        0.37            0.25       0.10      0.50 4.47
      Barry  EVE      FWD    0.91 0.87           1.86      1.89        0.10            0.00       0.00      0.68 4.43
  Calafiori  ARS      DEF    0.92 0.89           1.85      0.75        0.19            1.47       0.14      0.35 4.41
    Gonzalo  FUL      FWD    0.91 0.87           1.85      1.73        0.24            0.00       0.01      0.63 4.38
     Thiago  BRE      FWD    0.94 0.91           1.90      1.81        0.12            0.00       0.03      0.65 4.31
      Davis  IPS      DEF    0.95 0.92           1.90      1.13        0.24            0.91       0.23      0.35 4.27
      Wissa  NEW      FWD    0.93 0.89           1.88      1.82        0.14            0.00       0.01      0.66 4.22
   E.Le Fée  SUN      MID    0.94 0.91           1.90      1.00        0.54            0.23       0.29      0.38 4.21
     Enciso  IPS      MID    0.96 0.93           1.93      1.12        0.51            0.23       0.20      0.40 4.21
Gibbs-White  NFO      MID    0.97 0.95           1.94      1.22        0.34            0.25       0.04      0.41 4.15
```

```text
GW6 expected points, top 8 DEF
   player club position p_start p_60 pts_appearance pts_goals pts_assists pts_clean_sheet pts_defcon pts_bonus   ep
  Gabriel  ARS      DEF    0.95 0.92           1.90      0.51        0.16            1.53       0.59      0.31 4.62
Calafiori  ARS      DEF    0.92 0.89           1.85      0.75        0.19            1.47       0.14      0.35 4.41
    Davis  IPS      DEF    0.95 0.92           1.90      1.13        0.24            0.91       0.23      0.35 4.27
Tarkowski  EVE      DEF    0.95 0.92           1.90      0.37        0.15            1.15       0.79      0.23 4.14
 Khalaili  CRY      DEF    0.90 0.86           1.80      0.69        0.18            0.96       0.60      0.27 4.00
    Thiaw  NEW      DEF    0.95 0.92           1.90      0.58        0.10            1.02       0.60      0.25 4.00
   Botman  NEW      DEF    0.95 0.92           1.90      0.35        0.13            1.02       0.86      0.21 4.00
De Cuyper  BHA      DEF    0.93 0.90           1.87      0.75        0.42            1.05       0.08      0.32 3.98
```

Each column is one component, so you can see _why_ a player projects well. Take Gabriel's 4.62.
Beyond the 1.90 appearance points, most of it comes from clean sheets (1.53) and DefCon (0.59),
not from attacking returns.

### 10.3 Recommend with the full model

```bash
fpl recommend --model full --save
```

```text
Saved as run 15651932ae7d.

Private Team: GW6 recommendation, horizon GW6-9
Bank £1.0m | Free transfers 1

  Best transfer: OUT João Pedro (CHE) £7.6m (EP 2.60)  ->  IN Gonzalo (FUL) £6.0m (EP 4.38)
  Hits: 0. Gain over rolling the transfer, across GW6-9: +1.39 points (threshold 2.0)
  Verdict: gain below threshold: HOLD (roll the transfer).

Starting XI for GW6 (expected points incl. captain: 47.6)
  GKP  Verbruggen (BHA)              3.27
  DEF  Calafiori (ARS)               4.41
  DEF  Davis (IPS)                   4.27
  DEF  Mitchell (CRY)                3.38
  DEF  Gvardiol (MCI)                3.06
  MID  B.Fernandes (MUN)             5.12 (C)
  MID  Rogers (CHE)                  3.95
  MID  Ødegaard (ARS)                3.61
  MID  Slater (HUL)                  3.18
  FWD  Haaland (MCI)                 4.90 (V)
  FWD  Calvert-Lewin (LEE)           3.29
Bench, in order: Dubravka (TOT) 0.14, Tzolis (ARS) 2.87, João Pedro (CHE) 2.60, van Ewijk (COV) 1.56

Planned later (not an action now): GW7: Tzolis -> Mbeumo; GW8: Dubravka -> Kelleher; GW9: van Ewijk -> Thomas
```

The two models disagree:

- The skeleton wanted Tzolis → Groß (+4.7).
- The full model's best move is João Pedro → Gonzalo at +1.4, below the 2-point threshold. So
  it says roll the transfer.

The full model is the one that passed the gate. This result is from 26 September. Run it again
on Friday 9 October, when the press-conference news and the GW6 odds are in (Step 12).

**Checkpoint:** your two backtest outputs match the gate table, and `fpl recommend --model full`
works. Commit.

---

## Step 11 — Chip values up to GW19

**Goal:** for each GW from now to GW19, what Triple Captain, Bench Boost and Free Hit would add
with your current squad. The first chip set expires at the GW19 deadline, 1 January 2027 18:30 UTC
(20:30 in Kigali; §D).

`src/fpl/optimise/chips.py`

```python
"""Chip values per GW, so each chip can be planned for its best GW before it expires.

For each GW (01-reference.md H.10):
- Triple Captain: the captain's expected points (the extra 1×)
- Bench Boost: the expected points of your 4 bench players
- Free Hit: best legal squad's XI for that GW − your own XI, both with captain
All values use your current squad; they move as your squad changes, so rerun weekly.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from fpl.optimise.solver import SolverSettings, optimise
from fpl.team_state import TeamState


def chip_values(ep: pd.DataFrame, players: pd.DataFrame, team: TeamState) -> pd.DataFrame:
    rows = []
    for gw in ep.columns:
        single = ep[[gw]]
        own = optimise(single, players, team, SolverSettings(allow_transfers=False)).gws[0]
        free_hit_team = replace(team, free_transfers=15)
        best = optimise(single, players, free_hit_team, SolverSettings(max_free_transfers=15)).gws[0]
        rows.append(
            {
                "gw": gw,
                "your_xi": own.expected_points,
                "triple_captain": single.at[own.captain, gw],
                "bench_boost": sum(single.at[p, gw] for p in own.bench),
                "free_hit": best.expected_points - own.expected_points,
            }
        )
    return pd.DataFrame(rows)


def best_gws(values: pd.DataFrame, chips: list[str]) -> dict[str, int]:
    """The highest-value GW for each chip you still have."""
    return {chip: int(values.loc[values[chip].idxmax(), "gw"]) for chip in chips}
```

The Free Hit value reuses the solver. It gives the solver 15 free transfers for one GW, so the
solver builds the best legal squad from your budget.

Add to `cli.py`, above `# --- Entry point`:

```python
# --- Step 11: chips ------------------------------------------------------------------

@command("chips", "Value of Triple Captain, Bench Boost and Free Hit in each GW up to GW19",
         arg("--model", default="full"), arg("--to-gw", type=int, default=19))
def cmd_chips(settings: Settings, args) -> None:
    from fpl.optimise.chips import chip_values
    from fpl.projections import registry
    from fpl.projections.horizon import horizon_table
    from fpl.team_state import current_team

    with open_db(settings) as con:
        ctx, team = current_team(con, FplClient(settings), entry_id(settings))
        projector = registry.build(args.model, con, CURRENT_SEASON, first_gw=ctx.gw)
        ep = horizon_table(ctx, projector, list(range(ctx.gw, args.to_gw + 1)))
    report.print_chips(chip_values(ep, ctx.state, team), team)
```

Add to the end of `report.py`:

```python
# --- Step 11: chips ------------------------------------------------------------------

def print_chips(values: pd.DataFrame, team) -> None:
    print(f"Chip values for {team.team_name}'s current squad (expected points the chip adds)")
    print(table(values, "{:.1f}"))
    print()
    for chip in ("triple_captain", "bench_boost", "free_hit"):
        best = values.loc[values[chip].idxmax()]
        print(f"Best GW for {chip.replace('_', ' ')}: GW{int(best.gw)} (+{best[chip]:.1f})")
    print(f"Chips still available: {', '.join(team.chips_available) or 'none'}")
```

**Run** (about 20 seconds):

```bash
fpl chips
```

```text
Chip values for Private Team's current squad (expected points the chip adds)
 gw your_xi triple_captain bench_boost free_hit
  6    47.6            5.1         7.2      7.0
  7    49.2            6.6         6.5      9.0
  8    48.4            5.4         7.2      7.6
  9    47.2            5.9         6.9      7.1
 10    49.6            5.3         6.6      8.9
 11    49.2            6.2         7.1      6.9
 12    47.1            5.2         6.5      8.4
 13    47.7            5.8         7.1      7.1
 14    48.2            5.8         6.4     10.5
 15    48.1            5.6         6.8      6.8
 16    51.3            6.8         6.8      8.8
 17    47.3            5.3         6.8      7.4
 18    48.6            5.5         7.0      6.9
 19    49.0            5.7         6.5      9.1

Best GW for triple captain: GW16 (+6.8)
Best GW for bench boost: GW8 (+7.2)
Best GW for free hit: GW14 (+10.5)
Chips still available: wildcard (until GW19), freehit (until GW19), bboost (until GW19), 3xc (until GW19)
```

**How to use it.** The values are close together, because no double gameweeks are scheduled
before GW19. So:

- **Do not play a chip now.** GW6 is not a standout week for any chip.
- **Rerun weekly.** The values change whenever your squad or the fixtures change.
- **Play each chip when it is clearly above its other weeks, and before GW19 in any case.**
- A Wildcard has no single-GW value; plan it when the solver wants many transfers at once.

**Checkpoint:** a chip table for your team. Run `python -m pytest -q` (20 passed), then commit.

---

## Step 12 — The GW6 deadline runbook

Everything is built. This is the sequence for the deadline weekend. Times are UTC, with Kigali
time in brackets.

| When                                    | Do                                                                                                                                                                                                                 | Why                                                                                                     |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| Any day until 8 Oct                     | `fpl update` once a day (optional)                                                                                                                                                                                 | saves daily snapshots in `data/raw/`; keeps flags and prices current                                    |
| **Fri 9 Oct, 17:30 (19:30)**            | `fpl update && fpl odds && fpl fixtures`                                                                                                                                                                           | the press conferences are done and the GW6 odds are out; check that GW6 cells now show `*`              |
| Fri 9 Oct, 17:45 (19:45)                | `fpl recommend --model full --save`                                                                                                                                                                                | the transfer decision                                                                                   |
| Fri 9 Oct, 18:00 (20:00)                | Check by hand, for every player in the XI and every transfer target: FFScout team news \[10\] or RotoWire \[11\]. Use `fpl my-team` for your squad's flags, and `fpl projections --top 60` (`p_start`) for targets | the model cannot read press-conference quotes yet (Part 3 Step 25)                                      |
| **Fri 9 Oct, before 22:30 (Sat 00:30)** | **Make the transfer on the FPL site, if the verdict is MAKE**                                                                                                                                                      | the last price change before the deadline is at 23:00 UTC                                               |
| Sat 10 Oct, 08:00–09:30 (10:00–11:30)   | `fpl update && fpl projections --top 60`                                                                                                                                                                           | captain, vice and bench on the latest flags; change a transfer only if a player was ruled out overnight |
| **Sat 10 Oct, 10:00 (12:00)**           | **Deadline**                                                                                                                                                                                                       |                                                                                                         |
| Tue 13 Oct, after 08:00 (10:00)         | `fpl update && fpl settle`                                                                                                                                                                                         | fills in the realised points for both saved plans                                                       |

**Saturday morning:** FPL may hide a transfer made on Friday from the public endpoints until the
deadline passes. If it does, `fpl recommend` still shows your old squad. So on Saturday, choose the
captain, the vice-captain and the bench order yourself, from the `ep` column of
`fpl projections --top 60`, for the 15 players you now own.

**Rules for the weekend:**

- **Follow the verdict.** If it says HOLD, roll the transfer: you will have 2 free transfers for
  GW7.
- **Hits:** the default is none. Allow one with `--max-hits 1` only if a starter is ruled out
  and you have no free transfer.
- **Overrides:** if you override the model, write down why. After the GW, compare your real GW
  score with the `realised` column of `fpl settle`.

**Every GW after this one:** run the same sequence against that GW's deadline. The
`events` table has every deadline: `fpl sql "select gw, deadline from events where season = '2026-27' and not finished"`.

---

## Troubleshooting

| Symptom                                              | Cause                                                                                                                  | Fix                                                      |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| `command not found: fpl`                             | the environment is not active                                                                                          | `source .venv/bin/activate`                              |
| `No deadline or pre-deadline state for …`            | the database is missing that data                                                                                      | `fpl update`, and for past seasons `fpl load-history`    |
| `Catalog Error: Table with name odds does not exist` | Step 8 not run                                                                                                         | `fpl odds`                                               |
| `Add these clubs to CLUB_CODES`                      | football-data used a new club name                                                                                     | add it to `CLUB_CODES` in `ingest/odds.py`               |
| `git` error during `load-history`                    | git missing, or no network                                                                                             | `git --version`; run again (it resumes)                  |
| `Solver finished with status Infeasible`             | usually a squad the API returned that breaks a rule (for example 4 players from one club after a price or club change) | run `fpl my-team` and check the squad; report the case   |
| Numbers differ a little from this guide              | prices, flags and news change daily                                                                                    | expected; the backtest numbers (§I) should match exactly |

References \[10\] and \[11\] are listed in 01-reference.md.
