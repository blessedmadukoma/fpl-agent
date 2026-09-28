# FPL Agent 02 — Build, Part 1: from an empty folder to a GW6 recommendation

Version 3, 26 September 2026. Part 1 has eight steps, and each one ends with output you can check.
When you finish Step 6, you have a working recommendation for your own team (Private Team, entry
1234567): transfers, starting XI, captain and bench. Step 7 records each recommendation, so that
you can check it after the gameweek.

- Facts, formulas and target numbers are in **01-reference.md**. Links such as "§B" point there.
- **03-build-part2.md** makes the projections better and prepares the GW6 deadline.

Every file below is complete, and every command was run on 26 September 2026. The outputs shown
are the real outputs from that day. Your numbers will differ a little, because prices, flags and
news change daily.

---

## Before you start

### What you are building

`fpl` is a command-line program with one command per job, for example `fpl update` or
`fpl recommend`. It stores everything in one database file, `data/fpl.duckdb`. It has no server,
no Docker and no scheduler: you run a command when you want a result.

### How the code is organised

```
src/fpl/
  config.py        settings from .env                         (Step 0)
  fplapi.py        FPL API client; saves every response        (Step 0)
  cli.py           the commands; one block per step            (every step)
  report.py        everything that prints; one block per step  (every step)
  storage.py       DuckDB helpers                              (Step 1)
  ingest/          loaders: FPL API, history, odds             (Steps 1, 3, 8)
  scoring.py       FPL scoring rules                           (Step 2)
  checks.py        compares our scoring with FPL's             (Step 2)
  context.py       GwContext: what was known at a deadline     (Step 4)
  backtest/        replay a past season and score a model      (Steps 4, 8, 9)
  projections/     models that output expected points          (Steps 4, 6, 8-10)
  team_state.py    your squad, bank, FTs, chips                (Step 5)
  optimise/        solver, selling prices, chips               (Steps 5, 6, 11)
  recommend.py     projections + squad + solver                (Step 6)
  runs.py          save and settle recommendations             (Step 7)
tests/             pytest tests, added step by step
```

The code follows five rules:

1. **Library code never prints.** It returns data (DataFrames or dataclasses). Only `report.py`
   prints, and only `cli.py` opens the database.
2. **`cli.py` is thin.** Each command opens resources, calls one library function and hands the
   result to `report.py`.
3. **Every loader can run again.** A loader replaces only the rows it owns, for example "season
   2026-27", so running `fpl update` twice is safe.
4. **One leakage guard.** Every model reads a `GwContext` (Step 4). It contains only what was known
   at a deadline, so the same model code runs on history and on the next GW.
5. **Every model is a function** from a `GwContext` to expected points per player. To change a
   model you change one function, and the backtest tells you whether the change helped.

### How to use this guide

- All paths are relative to the project folder, `~/fpl-agent`.
- Use a code editor, for example VS Code (run `code .` in the project folder). Do not use
  TextEdit: it saves rich text and changes quotes.
- Create each file at the path shown, with exactly the content shown. Copying is fine.
- `cli.py` and `report.py` grow by one block per step. Paste each new block **above the line
  `# --- Entry point`** in `cli.py`, or **at the end** of `report.py`.
- Run the command, and compare your output with the expected output.
- Commit after each step: `git add -A && git commit -m "Step 1"` (use the step number). If a later
  step breaks something, `git diff` shows what changed.

---

## Step 0 — Environment

**Goal:** a Python project that installs, and one command (`fpl doctor`) that talks to the FPL API.

### 0.1 Clear what you built before

You made folders plus `.env`, `compose.yml` and a `Dockerfile` from the previous guide. Docker is not
needed on a laptop. If that folder is `~/fpl-agent`, rename it with `mv ~/fpl-agent ~/fpl-old`, so that
you start clean. Moving to a server comes later (Step 13).

### 0.2 Check the tools

Open Terminal and run:

```bash
python3 --version
git --version
```

You need Python 3.11, 3.12 or 3.13; 3.12 is recommended.

- **If Python is older than 3.11:** macOS ships an old Python. Install a new one with Homebrew
  (`brew install python@3.12`), or with the installer from python.org. Then use `python3.12`
  instead of `python3` in 0.7. Apple-silicon and Intel Macs both work.
- **If `git` is missing:** macOS offers to install the Command Line Tools. Accept.

### 0.3 Create the project

If you have never used git on this Mac, set your name once (any name and e-mail address work):

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

Then create the project:

```bash
mkdir -p ~/fpl-agent && cd ~/fpl-agent
git init
mkdir -p src/fpl/ingest src/fpl/backtest src/fpl/projections src/fpl/optimise tests data
touch src/fpl/__init__.py src/fpl/ingest/__init__.py src/fpl/backtest/__init__.py \
      src/fpl/projections/__init__.py src/fpl/optimise/__init__.py
```

The empty `__init__.py` files mark each folder as a Python package.

### 0.4 Project files

`pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "fpl-agent"
version = "0.1.0"
description = "Fantasy Premier League projections and transfer optimiser"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27",
    "duckdb>=1.1",
    "pandas>=2.2",
    "numpy>=1.26",
    "scipy>=1.11",
    "scikit-learn>=1.4",
    "pulp>=2.8",
    "highspy>=1.7",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
fpl = "fpl.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`pyproject.toml` lists the dependencies. It also creates the `fpl` command
(`[project.scripts]`), and it tells Python that the code lives in `src/`.

`.gitignore`

```text
.env
.venv/
data/
__pycache__/
*.egg-info/
.pytest_cache/
```

`.env.example`

```text
# Copy this file to .env and fill it in. Never commit .env.
FPL_ENTRY_ID=
# Optional: where data is stored (default: ./data inside the project)
# FPL_DATA_DIR=
```

### 0.5 Settings and the API client

`src/fpl/config.py`

```python
"""Project settings: read once from the environment (.env) and passed around explicitly."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

CURRENT_SEASON = "2026-27"
HISTORY_SEASON = "2025-26"


@dataclass(frozen=True)
class Settings:
    entry_id: int | None
    data_dir: Path
    user_agent: str = "fpl-agent/0.1 (personal research project)"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "fpl.duckdb"

    @property
    def raw_dir(self) -> Path:
        """Every API response is saved here, so any result can be reproduced later."""
        return self.data_dir / "raw"

    @property
    def cache_dir(self) -> Path:
        """Downloaded third-party files (historical data, odds)."""
        return self.data_dir / "cache"


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    entry = os.getenv("FPL_ENTRY_ID", "").strip()
    data_dir = Path(os.getenv("FPL_DATA_DIR", PROJECT_ROOT / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(entry_id=int(entry) if entry else None, data_dir=data_dir)
```

`Settings` is a frozen dataclass. It is created once, then passed to whatever needs it, so no module
reads environment variables on its own.

`src/fpl/fplapi.py`

```python
"""Small client for the public FPL API.

Every response is also written to data/raw/ as gzipped JSON. That is the "snapshot":
the API changes in place and keeps no history, so the raw file is the only record.
"""

from __future__ import annotations

import gzip
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from fpl.config import Settings

log = logging.getLogger(__name__)

BASE_URL = "https://fantasy.premierleague.com/api/"


class FplClient:
    def __init__(self, settings: Settings, save_raw: bool = True) -> None:
        self._settings = settings
        self._save_raw = save_raw
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": settings.user_agent},
            timeout=30.0,
            follow_redirects=True,
        )

    def get(self, path: str, retries: int = 3) -> Any:
        """GET one endpoint, e.g. "bootstrap-static/". Retries on network errors and 5xx."""
        for attempt in range(1, retries + 1):
            try:
                response = self._http.get(path)
                if response.status_code < 500:
                    response.raise_for_status()
                    data = response.json()
                    if self._save_raw:
                        self._write_raw(path, data)
                    return data
                log.warning("%s returned %s (attempt %d)", path, response.status_code, attempt)
            except httpx.TransportError as exc:
                log.warning("%s failed: %s (attempt %d)", path, exc, attempt)
            time.sleep(2**attempt)
        raise RuntimeError(f"FPL API request failed after {retries} attempts: {path}")

    # Named helpers, so callers never build URLs by hand.
    def bootstrap(self) -> dict:
        return self.get("bootstrap-static/")

    def fixtures(self) -> list[dict]:
        return self.get("fixtures/")

    def live(self, gw: int) -> dict:
        return self.get(f"event/{gw}/live/")

    def element_summary(self, element: int) -> dict:
        return self.get(f"element-summary/{element}/")

    def entry(self, entry_id: int) -> dict:
        return self.get(f"entry/{entry_id}/")

    def entry_history(self, entry_id: int) -> dict:
        return self.get(f"entry/{entry_id}/history/")

    def entry_transfers(self, entry_id: int) -> list[dict]:
        return self.get(f"entry/{entry_id}/transfers/")

    def entry_picks(self, entry_id: int, gw: int) -> dict:
        return self.get(f"entry/{entry_id}/event/{gw}/picks/")

    def _write_raw(self, path: str, data: Any) -> None:
        now = datetime.now(timezone.utc)
        slug = re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")
        folder = self._settings.raw_dir / now.strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{now.strftime('%H%M%S')}_{slug}.json.gz"
        with gzip.open(target, "wt", encoding="utf-8") as fh:
            json.dump(data, fh)
```

`FplClient` is the only code that makes HTTP requests to the FPL API. It retries on network errors
and on server errors. It saves every response to `data/raw/`, so every command you run adds to a
snapshot history.

### 0.6 The command line

`src/fpl/__main__.py`

```python
from fpl.cli import main

main()
```

`src/fpl/cli.py`

```python
"""Command-line entry point: `fpl <command>` (or `python -m fpl <command>`).

Each command is a small function: open resources, call one piece of the library, print.
The library modules never print, so they stay easy to test and reuse. Commands import
what they need inside the function, so each build step only needs its own modules.
"""

from __future__ import annotations

import argparse
import logging
import platform
from importlib.metadata import version

from fpl import report
from fpl.config import CURRENT_SEASON, HISTORY_SEASON, Settings, load_settings
from fpl.fplapi import FplClient

COMMANDS: dict[str, tuple] = {}


def command(name: str, help_text: str, *arguments):
    """Register a function as a sub-command. `arguments` are arg(...) values."""
    def register(func):
        COMMANDS[name] = (func, help_text, arguments)
        return func
    return register


def arg(*flags, **kwargs):
    return flags, kwargs


def open_db(settings: Settings):
    from fpl.storage import connect

    return connect(settings)


def entry_id(settings: Settings) -> int:
    if not settings.entry_id:
        raise SystemExit("Set FPL_ENTRY_ID in .env first (see `fpl doctor`).")
    return settings.entry_id


# --- Step 0: environment -------------------------------------------------------------

@command("doctor", "Check the Python environment, the API and your settings")
def cmd_doctor(settings: Settings, args) -> None:
    print(f"Python       {platform.python_version()}")
    for package in ["httpx", "duckdb", "pandas", "numpy", "scipy", "scikit-learn", "pulp", "highspy"]:
        print(f"{package:<12} {version(package)}")
    boot = FplClient(settings, save_raw=False).bootstrap()
    next_event = next(e for e in boot["events"] if not e["finished"])
    print(f"FPL API      ok: {len(boot['elements'])} players, next deadline GW{next_event['id']} "
          f"{next_event['deadline_time']}")
    print(f"Entry ID     {settings.entry_id or 'NOT SET: add FPL_ENTRY_ID to .env'}")
    print(f"Data folder  {settings.data_dir}")


# --- Entry point (keep this at the bottom) --------------------------------------------

def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request is too noisy
    parser = argparse.ArgumentParser(prog="fpl", description="FPL projections and optimiser")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (func, help_text, arguments) in COMMANDS.items():
        p = sub.add_parser(name, help=help_text)
        for flags, kwargs in arguments:
            p.add_argument(*flags, **kwargs)
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    args.func(load_settings(), args)
```

The `@command(...)` decorator adds a function to `COMMANDS`, and `main()` builds one sub-command
per entry. To add a command in a later step, paste a new decorated function. You never edit
`main()`.

Some names imported at the top, for example `CURRENT_SEASON`, stay unused until later steps. That
is expected.

`src/fpl/report.py`

```python
"""Everything that prints. Library code returns data; this module turns it into text."""

from __future__ import annotations

import pandas as pd

POSITION_ORDER = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}


def table(df: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    """Format a DataFrame for the terminal with consistent number formatting."""
    formatters = {c: floatfmt.format for c in df.columns if pd.api.types.is_float_dtype(df[c])}
    return df.to_string(index=False, formatters=formatters)


def money(tenths: float) -> str:
    return f"£{tenths / 10:.1f}m"
```

### 0.7 Install and run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
```

- `python3 -m venv .venv` makes a private Python environment for this project.
- `source .venv/bin/activate` switches to it. In every new terminal window, run
  `cd ~/fpl-agent && source .venv/bin/activate` first.
- `pip install -e` installs in editable mode: your code changes take effect without
  reinstalling.

Open `.env` in your editor (`code .env`; Finder hides files that start with a dot) and set
`FPL_ENTRY_ID=1234567`. Then run:

```bash
fpl doctor
```

**Expected output** (versions may be newer; the data folder will be `/Users/<you>/fpl-agent/data`):

```text
Python       3.11.15
httpx        0.28.1
duckdb       1.5.5
pandas       3.0.6
numpy        2.4.6
scipy        1.17.1
scikit-learn 1.9.1
pulp         3.3.2
highspy      1.15.1
FPL API      ok: 667 players, next deadline GW6 2026-10-10T10:00:00Z
Entry ID     1234567
Data folder  /home/claude/fpl-agent/data
```

**If it fails:**

- `command not found: fpl`: activate the environment with `source .venv/bin/activate`.
- `ModuleNotFoundError: fpl`: run `pip install -e ".[dev]"` from the project folder.

**Checkpoint:** `fpl doctor` shows the next deadline and your entry ID. Commit.

---

## Step 1 — Download the current season

**Goal:** the database holds every player, fixture and finished GW of 2026/27.

`src/fpl/storage.py`

```python
"""DuckDB helpers. The whole database is one file: data/fpl.duckdb.

Tables that hold several seasons have a `season` column. A loader replaces only the rows
it owns (for example one season, or one season and GW), so every loader can be re-run.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from fpl.config import Settings


def connect(settings: Settings) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(settings.db_path))


def table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    sql = "select count(*) from information_schema.tables where table_name = ?"
    return con.execute(sql, [table]).fetchone()[0] > 0


def replace_rows(con: duckdb.DuckDBPyConnection, table: str, df: pd.DataFrame, **keys) -> None:
    """Delete the rows of `table` that match `keys`, then insert `df`.

    Example: replace_rows(con, "player_gw", df, season="2026-27")
    Creates the table from `df` if it does not exist yet.
    """
    con.register("_incoming", df)
    try:
        if not table_exists(con, table):
            con.execute(f"create table {table} as select * from _incoming")
            return
        if keys:
            where = " and ".join(f"{column} = ?" for column in keys)
            con.execute(f"delete from {table} where {where}", list(keys.values()))
        con.execute(f"insert into {table} by name select * from _incoming")
    finally:
        con.unregister("_incoming")


def query(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> pd.DataFrame:
    return con.execute(sql, params or []).df()
```

`replace_rows` is the only way data enters the database. It deletes the rows it owns, for example
`season="2026-27"`, then inserts the new ones.

`src/fpl/ingest/current.py`

```python
"""Load the current season from the live FPL API into DuckDB."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from fpl.config import CURRENT_SEASON
from fpl.fplapi import FplClient
from fpl.storage import replace_rows

POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}  # FPL element_type -> position

# Per-player stats we keep from event/{gw}/live. Numeric strings (xG) are cast to float.
LIVE_STATS = [
    "minutes", "starts", "total_points", "goals_scored", "assists", "clean_sheets",
    "goals_conceded", "saves", "bonus", "bps", "defensive_contribution",
    "expected_goals", "expected_assists", "expected_goals_conceded",
    "yellow_cards", "red_cards", "own_goals", "penalties_saved", "penalties_missed",
]


def update_current(client: FplClient, con) -> dict:
    """Fetch bootstrap, fixtures and every finished GW; write them for CURRENT_SEASON."""
    boot = client.bootstrap()
    season = CURRENT_SEASON

    events = events_frame(boot, season)
    teams = teams_frame(boot, season)
    fixtures = fixtures_frame(client.fixtures(), season)
    players = players_frame(boot, season)
    finished = events.loc[events.finished, "gw"].tolist()
    player_gw = pd.concat([player_gw_frame(client.live(gw), gw, players, season) for gw in finished])
    next_gw = int(events.loc[~events.finished, "gw"].min())
    state = state_frame(boot, season, next_gw, snapshot_time=datetime.now(timezone.utc))

    rules = pd.DataFrame([{"season": season, "game_config": json.dumps(boot["game_config"])}])
    for table, df in [("events", events), ("teams", teams), ("fixtures", fixtures),
                      ("player_gw", player_gw), ("rules", rules)]:
        replace_rows(con, table, df, season=season)
    replace_rows(con, "state", state, season=season, gw=next_gw)

    return {
        "season": season,
        "players": len(players),
        "finished_gws": finished,
        "player_gw_rows": len(player_gw),
        "next_gw": next_gw,
        "next_deadline": events.loc[events.gw == next_gw, "deadline"].iloc[0],
    }


def events_frame(boot: dict, season: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": season,
            "gw": e["id"],
            "deadline": pd.Timestamp(e["deadline_time"]),
            "finished": bool(e["finished"]),
        }
        for e in boot["events"]
    )


def teams_frame(boot: dict, season: str) -> pd.DataFrame:
    return pd.DataFrame(
        {"season": season, "team_id": t["id"], "name": t["name"], "short_name": t["short_name"]}
        for t in boot["teams"]
    )


def fixtures_frame(fixtures: list[dict], season: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": season,
            "fixture_id": f["id"],
            "gw": f["event"],
            "kickoff": pd.Timestamp(f["kickoff_time"]) if f["kickoff_time"] else pd.NaT,
            "team_h": f["team_h"],
            "team_a": f["team_a"],
            "goals_h": f["team_h_score"],
            "goals_a": f["team_a_score"],
            "finished": bool(f["finished"]),
        }
        for f in fixtures
    )


def players_frame(boot: dict, season: str) -> pd.DataFrame:
    """Current snapshot of every player (prices, status, flags)."""
    return pd.DataFrame(_player_row(p, season) for p in boot["elements"])


def state_frame(boot: dict, season: str, gw: int, snapshot_time) -> pd.DataFrame:
    """Pre-deadline state for one GW: the inputs a projection may use for that GW."""
    df = players_frame(boot, season)
    df.insert(1, "gw", gw)
    df["snapshot_time"] = pd.Timestamp(snapshot_time)
    return df


def _player_row(p: dict, season: str) -> dict:
    return {
        "season": season,
        "element": p["id"],
        "code": p["code"],
        "web_name": p["web_name"],
        "team": p["team"],
        "position": POSITIONS[p["element_type"]],
        "now_cost": p["now_cost"],
        "cost_change_start": p["cost_change_start"],
        "status": p["status"],
        "chance": p["chance_of_playing_next_round"],
        "news": p["news"],
        "news_added": pd.Timestamp(p["news_added"]) if p.get("news_added") else pd.NaT,
        "ep_next": float(p["ep_next"] or 0),
        "form": float(p["form"] or 0),
        "ppg": float(p["points_per_game"] or 0),
        "selected": float(p["selected_by_percent"] or 0),
        "penalties_order": p.get("penalties_order"),
        "loan_ineligible_gws": ",".join(
            str(r["gameweek"]) for r in p.get("scout_risks") or [] if r.get("property") == "loan_ineligible"
        ),
    }


def player_gw_frame(live: dict, gw: int, players: pd.DataFrame, season: str) -> pd.DataFrame:
    """One row per player per finished GW, with GW-total stats."""
    rows = []
    for element in live["elements"]:
        if not element["explain"]:  # the player's team had no fixture (blank GW)
            continue
        stats = element["stats"]
        row = {"season": season, "gw": gw, "element": element["id"], "n_fixtures": len(element["explain"])}
        row.update({key: float(stats[key]) for key in LIVE_STATS})
        rows.append(row)
    df = pd.DataFrame(rows)
    meta = players[["element", "position", "team"]]
    return df.merge(meta, on="element", how="left")
```

The API data becomes six tables:

| Table       | Holds                                     |
| ----------- | ----------------------------------------- |
| `events`    | GW deadlines                              |
| `teams`     | clubs                                     |
| `fixtures`  | every fixture, with results               |
| `player_gw` | one row per player per finished GW        |
| `rules`     | the scoring coefficients                  |
| `state`     | the pre-deadline snapshot for the next GW |

`state` is the most important table. It holds what a model may use for a GW: status, flag, news,
price and `ep_next`.

Add to `cli.py`, above `# --- Entry point`:

```python
# --- Step 1: current season ----------------------------------------------------------

@command("update", "Download the current season from the FPL API into the database")
def cmd_update(settings: Settings, args) -> None:
    from fpl.ingest.current import update_current

    with open_db(settings) as con:
        summary = update_current(FplClient(settings), con)
    report.print_update(summary)


@command("sql", "Run a SQL query on the database and print the result", arg("query"))
def cmd_sql(settings: Settings, args) -> None:
    with open_db(settings) as con:
        print(report.table(con.execute(args.query).df()))
```

Add to the end of `report.py`:

```python
# --- Step 1: current season ----------------------------------------------------------

def print_update(summary: dict) -> None:
    print(f"Season {summary['season']}: {summary['players']} players")
    print(f"Finished GWs: {summary['finished_gws']} ({summary['player_gw_rows']} player-GW rows)")
    print(f"Next: GW{summary['next_gw']}, deadline {summary['next_deadline']:%a %d %b %Y %H:%M} UTC")
```

**Run:**

```bash
fpl update
fpl sql "select gw, count(*) as players, count(*) filter (where minutes > 0) as played, cast(sum(total_points) as integer) as points from player_gw where season = '2026-27' group by gw order by gw"
```

**Expected output:**

```text
Season 2026-27: 667 players
Finished GWs: [1, 2, 3, 4, 5] (3216 player-GW rows)
Next: GW6, deadline Sat 10 Oct 2026 10:00 UTC
```

```text
 gw  players  played  points
  1      610     310     948
  2      626     312     891
  3      654     307     912
  4      659     307     921
  5      667     302     966
```

`fpl sql` runs any query on the database. Use it to look around, for example
`fpl sql "describe state"`.

**Checkpoint:** 667 players, GWs 1–5 finished, next deadline Saturday 10 October 10:00 UTC. Commit.

---

## Step 2 — The scoring function, checked against FPL

**Goal:** a function that turns match stats into FPL points and agrees with FPL for every player.
Every projection is this same arithmetic with expected values, so this is the contract for
everything that follows.

`src/fpl/scoring.py`

```python
"""FPL scoring rules and the realised-points function.

Coefficients come from bootstrap-static -> game_config.scoring. The API does not give the
thresholds (60 minutes, per 2 goals conceded, per 3 saves, defensive contribution 10/12),
so they live here, in one place. The scoring check (fpl check-scoring) is what tells you
if FPL changes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

LONG_PLAY_MINUTES = 60
GOALS_CONCEDED_PER_POINT = 2
SAVES_PER_POINT = 3
DEFCON_THRESHOLD = {"GKP": 10**9, "DEF": 10, "MID": 12, "FWD": 12}  # GKP cannot earn it

# Stats that score a fixed coefficient per unit.
PER_UNIT_STATS = (
    "goals_scored",
    "assists",
    "clean_sheets",
    "penalties_saved",
    "penalties_missed",
    "yellow_cards",
    "red_cards",
    "own_goals",
    "bonus",
)


@dataclass(frozen=True)
class Rules:
    coefficients: Mapping[str, int | Mapping[str, int]]

    @classmethod
    def from_game_config(cls, game_config: Mapping) -> "Rules":
        return cls(coefficients=dict(game_config["scoring"]))

    def points(self, stat: str, position: str) -> int:
        """Points per unit of `stat` for `position` (some coefficients depend on position)."""
        value = self.coefficients[stat]
        return value[position] if isinstance(value, Mapping) else value


def score(stats: Mapping[str, float], position: str, rules: Rules) -> int:
    """Realised FPL points for one player in one fixture."""
    minutes = stats.get("minutes", 0)
    total = 0
    if minutes >= LONG_PLAY_MINUTES:
        total += rules.points("long_play", position)
    elif minutes > 0:
        total += rules.points("short_play", position)

    for stat in PER_UNIT_STATS:
        total += int(stats.get(stat, 0)) * rules.points(stat, position)

    conceded = int(stats.get("goals_conceded", 0))
    total += (conceded // GOALS_CONCEDED_PER_POINT) * rules.points("goals_conceded", position)

    saves = int(stats.get("saves", 0))
    total += (saves // SAVES_PER_POINT) * rules.points("saves", position)

    if stats.get("defensive_contribution", 0) >= DEFCON_THRESHOLD[position]:
        total += rules.points("defensive_contribution", position)
    return total
```

`src/fpl/checks.py`

```python
"""Checks that compare our code with the official numbers."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from fpl.scoring import Rules, score
from fpl.storage import query, table_exists


@dataclass
class ScoringCheck:
    season: str
    source: str
    checked: int
    skipped: int
    mismatches: pd.DataFrame


def load_rules(con, season: str) -> Rules:
    game_config = query(con, "select game_config from rules where season = ?", [season])
    if game_config.empty:
        raise LookupError(f"No scoring rules stored for {season}. Run the loader first.")
    return Rules.from_game_config(json.loads(game_config.iloc[0, 0]))


def check_scoring(con, season: str) -> ScoringCheck:
    """Recompute every player's points and list the rows that differ from FPL's total_points.

    Uses per-fixture rows where we have them (history), else GW rows with one fixture.
    Floors (goals conceded, saves) apply per fixture, so double-GW totals cannot be checked.
    """
    rules = load_rules(con, season)
    if table_exists(con, "player_fixture") and _has_season(con, "player_fixture", season):
        rows, source, skipped = query(con, "select * from player_fixture where season = ?", [season]), "player_fixture", 0
    else:
        all_rows = query(con, "select * from player_gw where season = ?", [season])
        rows = all_rows[all_rows.n_fixtures == 1]
        source, skipped = "player_gw", len(all_rows) - len(rows)

    ours = rows.apply(lambda r: score(r.to_dict(), r["position"], rules), axis=1)
    bad = rows.assign(ours=ours)[ours != rows["total_points"]]
    columns = ["gw", "element", "position", "minutes", "total_points", "ours"]
    return ScoringCheck(season, source, len(rows), skipped, bad[columns])


def _has_season(con, table: str, season: str) -> bool:
    return query(con, f"select count(*) as n from {table} where season = ?", [season]).n.iloc[0] > 0
```

`tests/test_scoring.py`

```python
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
    assert score({"minutes": 90, "clean_sheets": 1, "goals_scored": 1}, "DEF", RULES) == 2 + 4 + 6


def test_goals_conceded_floor_per_two():
    assert score({"minutes": 90, "goals_conceded": 3}, "GKP", RULES) == 2 - 1
    assert score({"minutes": 90, "goals_conceded": 4}, "DEF", RULES) == 2 - 2
    assert score({"minutes": 90, "goals_conceded": 4}, "MID", RULES) == 2


def test_saves_floor_per_three():
    assert score({"minutes": 90, "saves": 5}, "GKP", RULES) == 2 + 1
    assert score({"minutes": 90, "saves": 6}, "GKP", RULES) == 2 + 2


def test_defensive_contribution_thresholds():
    assert score({"minutes": 90, "defensive_contribution": 10}, "DEF", RULES) == 4
    assert score({"minutes": 90, "defensive_contribution": 11}, "MID", RULES) == 2
    assert score({"minutes": 90, "defensive_contribution": 12}, "MID", RULES) == 4
    assert score({"minutes": 90, "defensive_contribution": 15}, "GKP", RULES) == 2
```

The tests use hand-made cases, so they document the rules, for example "4 goals conceded costs a
defender 2 points". `check_scoring` compares the function with every real row.

Add to `cli.py`, above `# --- Entry point`:

```python
# --- Step 2: scoring -----------------------------------------------------------------

@command("check-scoring", "Recompute every player's points and compare with FPL",
         arg("--season", default=CURRENT_SEASON))
def cmd_check_scoring(settings: Settings, args) -> None:
    from fpl.checks import check_scoring

    with open_db(settings) as con:
        result = check_scoring(con, args.season)
    report.print_scoring_check(result)
```

Add to the end of `report.py`:

```python
# --- Step 2: scoring -----------------------------------------------------------------

def print_scoring_check(result) -> None:
    print(f"Season {result.season}, source {result.source}: checked {result.checked:,} rows"
          + (f", skipped {result.skipped:,} double-GW rows" if result.skipped else ""))
    if result.mismatches.empty:
        print("0 mismatches. The scoring function matches FPL exactly.")
    else:
        print(f"{len(result.mismatches):,} MISMATCHES. First 20:")
        print(result.mismatches.head(20).to_string(index=False))
```

**Run:**

```bash
fpl check-scoring
python -m pytest -q tests/test_scoring.py
```

**Expected output:**

```text
Season 2026-27, source player_gw: checked 3,216 rows
0 mismatches. The scoring function matches FPL exactly.
```

```text
.....                                                                    [100%]
5 passed in 0.02s
```

**If you see mismatches:** the table lists the players who differ. Compare their stats with §D.
The API is right, so the fix is always in `scoring.py`.

**Checkpoint:** 0 mismatches. Commit.

---

## Step 3 — Last season, and what was known before each deadline

**Goal:** load 2025/26 results (vaastav) and one pre-deadline snapshot per GW (fplcache). These
make the backtest in Step 4 honest: it only uses what you could have known at the time.

`src/fpl/ingest/download.py`

```python
"""Download a file once and keep it in data/cache/."""

from __future__ import annotations

from pathlib import Path

import httpx


def download(url: str, target: Path, refresh: bool = False) -> Path:
    """Fetch `url` to `target`. Re-download only if `refresh` or the file is missing."""
    if refresh or not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        response = httpx.get(url, timeout=60, follow_redirects=True)
        response.raise_for_status()
        target.write_bytes(response.content)
    return target
```

`src/fpl/ingest/history.py`

```python
"""Load historical data: last season's results (vaastav) and pre-deadline snapshots (fplcache).

- vaastav/Fantasy-Premier-League: one row per player per fixture, after the fixture.
- Randdalf/fplcache: raw bootstrap-static about four times a day since 2021. We take the
  last snapshot before each deadline: that is what a model could have known at the time.
"""

from __future__ import annotations

import json
import lzma
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from fpl.config import Settings
from fpl.ingest.current import LIVE_STATS, events_frame, state_frame, teams_frame
from fpl.ingest.download import download
from fpl.storage import replace_rows

VAASTAV_URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/{season}/{file}"
FPLCACHE_REPO = "https://github.com/Randdalf/fplcache.git"
VAASTAV_POSITIONS = {"GK": "GKP", "GKP": "GKP", "DEF": "DEF", "MID": "MID", "FWD": "FWD"}


@dataclass(frozen=True)
class SeasonWindow:
    """The dates of one FPL season, used to pick fplcache snapshots."""
    season: str
    start: datetime
    end: datetime

    @classmethod
    def for_season(cls, season: str) -> "SeasonWindow":
        first_year = int(season[:4])
        return cls(
            season,
            datetime(first_year, 7, 1, tzinfo=timezone.utc),
            datetime(first_year + 1, 6, 30, tzinfo=timezone.utc),
        )


# --- fplcache ----------------------------------------------------------------------

class FplCache:
    """A blob-less git clone: we list every file, then download only the ones we need."""

    def __init__(self, settings: Settings) -> None:
        self.repo = settings.cache_dir / "fplcache"

    def sync(self) -> None:
        if not (self.repo / ".git").exists():
            self.repo.parent.mkdir(parents=True, exist_ok=True)
            self._git("clone", "--filter=blob:none", "--no-checkout", FPLCACHE_REPO, str(self.repo),
                      cwd=self.repo.parent)
        else:
            self._git("fetch", "--filter=blob:none", "origin")
            self._git("reset", "--soft", "origin/HEAD")

    def index(self) -> pd.DataFrame:
        """Every snapshot path with its UTC timestamp (taken from the path)."""
        names = self._git("ls-tree", "-r", "--name-only", "HEAD", "cache").split()
        rows = []
        for name in names:
            parts = name.removesuffix(".json.xz").split("/")  # cache/Y/M/D/HHMM
            if len(parts) != 5:
                continue
            _, y, m, d, hm = parts
            time = datetime(int(y), int(m), int(d), int(hm[:2]), int(hm[2:]), tzinfo=timezone.utc)
            rows.append({"path": name, "time": time})
        return pd.DataFrame(rows).sort_values("time", ignore_index=True)

    def read(self, paths: list[str]) -> dict[str, dict]:
        """Download (if needed) and parse snapshots."""
        missing = [p for p in paths if not (self.repo / p).exists()]
        if missing:
            self._git("checkout", "HEAD", "--", *missing)
        return {p: json.loads(lzma.open(self.repo / p).read()) for p in paths}

    def _git(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(["git", *args], cwd=cwd or self.repo, capture_output=True, text=True, check=True)
        return result.stdout


def load_states_from_fplcache(settings: Settings, con, season: str, with_metadata: bool = True) -> dict:
    """Write one pre-deadline `state` snapshot per past GW.

    With `with_metadata`, also write that season's events, teams and scoring rules. Use it for
    past seasons only: for the current season, `fpl update` writes fresher versions.
    """
    cache = FplCache(settings)
    cache.sync()
    index = cache.index()
    window = SeasonWindow.for_season(season)
    in_season = index[(index.time >= window.start) & (index.time <= window.end)]

    latest_path = in_season.path.iloc[-1]
    latest = cache.read([latest_path])[latest_path]
    events = events_frame(latest, season)
    past = events[events.deadline < datetime.now(timezone.utc)]

    chosen = {}
    for gw, deadline in zip(past.gw, past.deadline):
        before = in_season[in_season.time < deadline]
        if not before.empty:
            chosen[int(gw)] = before.iloc[-1]
    snapshots = cache.read([row.path for row in chosen.values()])

    for gw, row in chosen.items():
        state = state_frame(snapshots[row.path], season, gw, snapshot_time=row.time)
        replace_rows(con, "state", state, season=season, gw=gw)

    if with_metadata:
        replace_rows(con, "events", events, season=season)
        replace_rows(con, "teams", teams_frame(latest, season), season=season)
        rules = pd.DataFrame([{"season": season, "game_config": json.dumps(latest["game_config"])}])
        replace_rows(con, "rules", rules, season=season)

    lead_hours = [(past.set_index("gw").deadline[gw] - row.time).total_seconds() / 3600 for gw, row in chosen.items()]
    return {"season": season, "gws": len(chosen), "median_lead_h": pd.Series(lead_hours).median(),
            "max_lead_h": max(lead_hours)}


# --- vaastav -----------------------------------------------------------------------

def load_vaastav_season(settings: Settings, con, season: str) -> dict:
    """Write `player_fixture`, `player_gw` and `fixtures` for a finished season.

    Needs the `teams` rows for that season (written by load_states_from_fplcache).
    """
    folder = settings.cache_dir / "vaastav" / season
    merged = pd.read_csv(download(VAASTAV_URL.format(season=season, file="gws/merged_gw.csv"), folder / "merged_gw.csv"))
    fixtures_raw = pd.read_csv(download(VAASTAV_URL.format(season=season, file="fixtures.csv"), folder / "fixtures.csv"))

    teams = con.execute("select team_id, name from teams where season = ?", [season]).df()
    team_ids = dict(zip(teams.name, teams.team_id))

    player_fixture = pd.DataFrame(
        {
            "season": season,
            "gw": merged["round"].astype(int),
            "fixture": merged["fixture"].astype(int),
            "element": merged["element"].astype(int),
            "position": merged["position"].map(VAASTAV_POSITIONS),
            "team": merged["team"].map(team_ids),
            **{stat: merged[stat].astype(float) for stat in LIVE_STATS},
        }
    )
    if player_fixture[["position", "team"]].isna().any().any():
        raise ValueError("Unmapped position or team name in vaastav data; check VAASTAV_POSITIONS and teams.")

    player_gw = (
        player_fixture.groupby(["season", "gw", "element", "position", "team"], as_index=False)
        .agg(**{stat: (stat, "sum") for stat in LIVE_STATS}, n_fixtures=("fixture", "count"))
    )
    fixtures = pd.DataFrame(
        {
            "season": season,
            "fixture_id": fixtures_raw["id"],
            "gw": fixtures_raw["event"],
            "kickoff": pd.to_datetime(fixtures_raw["kickoff_time"], utc=True),
            "team_h": fixtures_raw["team_h"],
            "team_a": fixtures_raw["team_a"],
            "goals_h": fixtures_raw["team_h_score"],
            "goals_a": fixtures_raw["team_a_score"],
            "finished": fixtures_raw["finished"].astype(bool),
        }
    )
    replace_rows(con, "player_fixture", player_fixture, season=season)
    replace_rows(con, "player_gw", player_gw, season=season)
    replace_rows(con, "fixtures", fixtures, season=season)
    return {"season": season, "player_fixture_rows": len(player_fixture), "player_gw_rows": len(player_gw),
            "fixtures": len(fixtures)}
```

Two design points:

- `FplCache` makes a **blob-less git clone**: it lists all 7,900 snapshots but downloads only the
  ~43 it needs. That is why this step needs `git`.
- For each GW, `load_states_from_fplcache` takes **the last snapshot before the deadline** and
  writes it to `state`. That is exactly what a model could have known.

Add to `cli.py`, above `# --- Entry point`:

```python
# --- Step 3: history -----------------------------------------------------------------

@command("load-history", "Download last season and the pre-deadline snapshots (under a minute)")
def cmd_load_history(settings: Settings, args) -> None:
    from fpl.ingest.history import load_states_from_fplcache, load_vaastav_season

    with open_db(settings) as con:
        past = load_states_from_fplcache(settings, con, HISTORY_SEASON)
        now = load_states_from_fplcache(settings, con, CURRENT_SEASON, with_metadata=False)
        results = load_vaastav_season(settings, con, HISTORY_SEASON)
    report.print_history_load(past, now, results)
```

Add to the end of `report.py`:

```python
# --- Step 3: history -----------------------------------------------------------------

def print_history_load(past: dict, now: dict, results: dict) -> None:
    for s in (past, now):
        print(f"{s['season']}: {s['gws']} pre-deadline snapshots "
              f"(median {s['median_lead_h']:.1f} h before the deadline, max {s['max_lead_h']:.1f} h)")
    print(f"{results['season']} results: {results['player_fixture_rows']:,} player-fixture rows, "
          f"{results['player_gw_rows']:,} player-GW rows, {results['fixtures']} fixtures")
```

**Run** (under a minute):

```bash
fpl load-history
fpl check-scoring --season 2025-26
```

**Expected output:**

```text
2025-26: 38 pre-deadline snapshots (median 4.3 h before the deadline, max 5.6 h)
2026-27: 5 pre-deadline snapshots (median 2.0 h before the deadline, max 6.5 h)
2025-26 results: 29,757 player-fixture rows, 29,338 player-GW rows, 380 fixtures
```

```text
Season 2025-26, source player_fixture: checked 29,757 rows
0 mismatches. The scoring function matches FPL exactly.
```

The second check scores every one of 29,757 player-fixtures of last season with 0 mismatches.

**Checkpoint:** 38 snapshots for 2025/26, 5 for 2026/27, 0 mismatches. Commit.

---

## Step 4 — The backtest harness and the baselines

**Goal:** a command that replays 2025/26 GW by GW, projects each GW with only what was known, and
scores the projection. Every model from now on must beat the numbers you get here.

`src/fpl/context.py`

```python
"""What was knowable at a GW deadline. Every projection takes one of these as input.

The leakage rule lives here and nowhere else: `history` only holds GWs before `gw`, and
`state` is the last snapshot before the deadline. A model that only reads a GwContext
cannot see the future.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fpl.config import CURRENT_SEASON
from fpl.storage import query


@dataclass(frozen=True)
class GwContext:
    season: str
    gw: int
    deadline: pd.Timestamp
    state: pd.DataFrame      # one row per player: status, flags, price, ep_next, ... at the deadline
    history: pd.DataFrame    # player_gw rows of this season with gw < self.gw
    fixtures: pd.DataFrame   # every fixture of the season (results only used for gw < self.gw)
    teams: pd.DataFrame

    def past_fixtures(self) -> pd.DataFrame:
        return self.fixtures[self.fixtures.gw < self.gw]


def load_context(con, season: str, gw: int) -> GwContext:
    deadline = query(con, "select deadline from events where season = ? and gw = ?", [season, gw])
    state = query(con, "select * from state where season = ? and gw = ?", [season, gw])
    if deadline.empty or state.empty:
        raise LookupError(f"No deadline or pre-deadline state for {season} GW{gw}. Run `fpl update`.")
    history = query(con, "select * from player_gw where season = ? and gw < ? order by gw", [season, gw])
    fixtures = query(con, "select * from fixtures where season = ?", [season])
    teams = query(con, "select * from teams where season = ?", [season])
    return GwContext(season, gw, deadline.deadline.iloc[0], state, history, fixtures, teams)


def next_gw(con, season: str = CURRENT_SEASON) -> int:
    """The first GW that has not finished: the one you are picking a team for."""
    events = query(con, "select gw from events where season = ? and not finished order by gw", [season])
    return int(events.gw.iloc[0])
```

`GwContext` is the leakage guard (§A). `history` holds only GWs before `gw`, and `state` is the
pre-deadline snapshot.

`src/fpl/backtest/metrics.py`

```python
"""Scores for projections. See 01-reference.md §B for why these and not MAE."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


def rmse(predicted: pd.Series, actual: pd.Series) -> float:
    return float(np.sqrt(((predicted - actual) ** 2).mean()))


def bias(predicted: pd.Series, actual: pd.Series) -> float:
    return float((predicted - actual).mean())


def mean_rank_correlation(frame: pd.DataFrame, predicted: str, actual: str, by: str = "gw") -> float:
    """Spearman correlation within each GW, averaged over GWs (the solver ranks within a GW)."""
    values = [
        spearmanr(group[predicted], group[actual]).statistic
        for _, group in frame.groupby(by)
        if group[predicted].nunique() > 1
    ]
    return float(np.nanmean(values))


def top_k(frame: pd.DataFrame, predicted: str, actual: str, k: int = 15, by: str = "gw") -> tuple[float, float]:
    """Mean projected and mean realised points of the k highest projections per GW."""
    ranks = frame.groupby(by)[predicted].rank(ascending=False, method="first")
    top = frame[ranks <= k]
    return float(top[predicted].mean()), float(top[actual].mean())


def log_loss(probability: pd.Series, outcome: pd.Series, eps: float = 1e-4) -> float:
    p = probability.clip(eps, 1 - eps)
    return float(-(outcome * np.log(p) + (1 - outcome) * np.log(1 - p)).mean())


def brier(probability: pd.Series, outcome: pd.Series) -> float:
    return float(((probability - outcome) ** 2).mean())
```

`src/fpl/backtest/replay.py`

```python
"""Replay a season GW by GW: project with only what was known, then compare with reality."""

from __future__ import annotations

import pandas as pd

from fpl.backtest import metrics
from fpl.context import load_context
from fpl.projections.baseline import Projector
from fpl.storage import query

POOL_R = "regular starters (3+ starts in previous 4 GWs)"
POOL_O = "owned by 1%+ at the deadline"
POOL_ALL = "all players"


def replay(con, season: str, projector: Projector, gws: range) -> pd.DataFrame:
    """One row per player per GW: projection `ep`, realised `pts` and pool flags."""
    outcomes = query(con, "select gw, element, total_points as pts, starts from player_gw where season = ?", [season])
    pools = pool_flags(outcomes)
    frames = []
    for gw in gws:
        ctx = load_context(con, season, gw)
        ep = projector(ctx).rename("ep").rename_axis("element").reset_index()
        ep["gw"] = gw
        ep = ep.merge(ctx.state[["element", "selected"]], on="element")
        frames.append(ep)
    projected = pd.concat(frames, ignore_index=True)
    # Inner join: a player with no fixture that GW has no outcome row and is left out.
    frame = projected.merge(outcomes[["gw", "element", "pts"]], on=["gw", "element"])
    frame = frame.merge(pools, on=["gw", "element"], how="left")
    frame["pool_R"] = frame.pool_R.fillna(False).astype(bool)
    frame["pool_O"] = frame.selected >= 1.0
    return frame


def pool_flags(outcomes: pd.DataFrame) -> pd.DataFrame:
    """Pool R membership per (gw, element), using only earlier GWs."""
    df = outcomes.sort_values(["element", "gw"]).copy()
    started = (df.starts > 0).astype(int)
    df["starts_last4"] = started.groupby(df.element).transform(
        lambda s: s.shift(1).rolling(4, min_periods=4).sum()
    )
    df["pool_R"] = df.starts_last4 >= 3
    return df[["gw", "element", "pool_R"]]


def summarise(frame: pd.DataFrame, k: int = 15) -> tuple[pd.DataFrame, dict]:
    """The metrics table used throughout the guide, plus the top-k check."""
    rows = []
    everyone = pd.Series(True, index=frame.index)
    for name, mask in [(POOL_R, frame.pool_R), (POOL_O, frame.pool_O), (POOL_ALL, everyone)]:
        part = frame[mask]
        rows.append(
            {
                "pool": name,
                "n": len(part),
                "rmse": metrics.rmse(part.ep, part.pts),
                "bias": metrics.bias(part.ep, part.pts),
                "rho": metrics.mean_rank_correlation(part, "ep", "pts"),
            }
        )
    projected, realised = metrics.top_k(frame, "ep", "pts", k=k)
    table = pd.DataFrame(rows)
    top = {"top_k": k, "projected": projected, "realised": realised}
    return table, top
```

`src/fpl/projections/baseline.py`

```python
"""Simple projections that need no model. They are the numbers every model must beat.

A projector takes a GwContext and returns expected points for that GW, one value per
player, as a Series indexed by element id.
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

from fpl.context import GwContext

Projector = Callable[[GwContext], pd.Series]


def _by_element(ctx: GwContext, values) -> pd.Series:
    return pd.Series(values.to_numpy(dtype=float), index=ctx.state.element.to_numpy(), name="ep")


def availability_factor(state: pd.DataFrame) -> pd.Series:
    """FPL's chance-of-playing flag as a factor: 1 when there is no flag."""
    return (state.chance.astype(float) / 100).fillna(1.0)


def ep_next(ctx: GwContext) -> pd.Series:
    """FPL's own projection (about form × chance of playing)."""
    return _by_element(ctx, ctx.state.ep_next)


def points_per_game(ctx: GwContext) -> pd.Series:
    return _by_element(ctx, ctx.state.ppg)


def form(ctx: GwContext) -> pd.Series:
    return _by_element(ctx, ctx.state.form)


def zero(ctx: GwContext) -> pd.Series:
    return _by_element(ctx, ctx.state.ep_next * 0)


def blend(ctx: GwContext) -> pd.Series:
    """0.5 × ep_next + 0.5 × PPG × flag. In the 2025/26 replay it beats both of its parts."""
    ppg_available = ctx.state.ppg * availability_factor(ctx.state)
    return _by_element(ctx, 0.5 * ctx.state.ep_next + 0.5 * ppg_available)


# Prior weight, in appearances. Tuned on the 2025/26 replay: k = 4 gives a bias near zero
# and halves the over-projection of the top 15 players per GW (01-reference.md §I).
SHRINK_APPEARANCES = 4


def shrunk_blend(ctx: GwContext, k: float = SHRINK_APPEARANCES) -> pd.Series:
    """The blend, pulled towards a typical player of the same position.

    A player with n appearances gets weight n / (n + k) on his own numbers. The prior is the
    position's mean points per appearance × his start rate × his availability flag.
    """
    raw = blend(ctx)
    played = ctx.history[ctx.history.minutes > 0]
    appearances = played.groupby("element").size().reindex(raw.index, fill_value=0)
    per_appearance = played.groupby("position").total_points.mean()
    start_rate = (ctx.history.starts > 0).groupby(ctx.history.element).mean().reindex(raw.index, fill_value=0.0)
    state = ctx.state.set_index("element")
    prior = state.position.map(per_appearance).fillna(0.0) * start_rate * availability_factor(state)
    return ((appearances * raw + k * prior) / (appearances + k)).rename("ep")


BASELINES: dict[str, Projector] = {
    "shrunk_blend": shrunk_blend,
    "blend": blend,
    "ep_next": ep_next,
    "ppg": points_per_game,
    "form": form,
    "zero": zero,
}
```

The **shrunk blend** is the skeleton projection. It starts from `0.5 × ep_next + 0.5 × PPG`, and
pulls players with few appearances towards the average for their position. At GW6 a player has at
most 5 appearances, so he gets at most 5/(5+4) = 56% weight on his own numbers. The value k = 4
was tuned on the replay: it gives a bias near zero.

Create `src/fpl/projections/registry.py` (Step 10 replaces it with a version that adds the full
model):

`src/fpl/projections/registry.py`

```python
"""Look up a projection model by name, so the CLI, backtest and solver can switch models."""

from __future__ import annotations

from fpl.config import CURRENT_SEASON
from fpl.projections.baseline import BASELINES, Projector

MODELS = list(BASELINES)


def build(name: str, con=None, season: str = CURRENT_SEASON, first_gw: int = 1) -> Projector:
    """Return the model called `name`. Baselines need no training; step 10 adds a trained model."""
    if name in BASELINES:
        return BASELINES[name]
    raise SystemExit(f"Unknown model '{name}'. Choose from: {', '.join(MODELS)}")
```

Add to `cli.py`, above `# --- Entry point`:

```python
# --- Step 4: backtest ----------------------------------------------------------------

@command("backtest", "Score a projection model on a past season",
         arg("--model", default="shrunk_blend"), arg("--season", default=HISTORY_SEASON),
         arg("--from-gw", type=int, default=5), arg("--to-gw", type=int, default=38))
def cmd_backtest(settings: Settings, args) -> None:
    from fpl.backtest.replay import replay, summarise
    from fpl.projections import registry

    with open_db(settings) as con:
        projector = registry.build(args.model, con, args.season, first_gw=args.from_gw)
        frame = replay(con, args.season, projector, range(args.from_gw, args.to_gw + 1))
    report.print_backtest(args.model, args.season, args.from_gw, args.to_gw, *summarise(frame))
```

Add to the end of `report.py`:

```python
# --- Step 4: backtest ----------------------------------------------------------------

def print_backtest(model: str, season: str, first: int, last: int, metrics: pd.DataFrame, top: dict) -> None:
    print(f"Model '{model}', {season} GW{first}-{last}")
    print(table(metrics))
    print(f"Top {top['top_k']} per GW: projected {top['projected']:.2f}, realised {top['realised']:.2f} "
          f"(over-projection {top['projected'] - top['realised']:.2f})")
```

**Run:**

```bash
fpl backtest --model ep_next
fpl backtest --model blend
fpl backtest
```

(`fpl backtest` with no model uses `shrunk_blend`.)

**Expected output:**

```text
Model 'ep_next', 2025-26 GW5-38
                                          pool     n rmse  bias  rho
regular starters (3+ starts in previous 4 GWs)  6421 3.43  0.28 0.28
                  owned by 1%+ at the deadline  6359 3.37  0.09 0.50
                                   all players 26406 2.13 -0.06 0.70
Top 15 per GW: projected 7.96, realised 4.34 (over-projection 3.62)
```

```text
Model 'blend', 2025-26 GW5-38
                                          pool     n rmse bias  rho
regular starters (3+ starts in previous 4 GWs)  6421 3.19 0.22 0.30
                  owned by 1%+ at the deadline  6359 3.12 0.22 0.52
                                   all players 26406 1.99 0.07 0.75
Top 15 per GW: projected 6.58, realised 4.39 (over-projection 2.19)
```

```text
Model 'shrunk_blend', 2025-26 GW5-38
                                          pool     n rmse  bias  rho
regular starters (3+ starts in previous 4 GWs)  6421 3.12 -0.03 0.32
                  owned by 1%+ at the deadline  6359 3.05 -0.02 0.53
                                   all players 26406 1.94 -0.06 0.78
Top 15 per GW: projected 5.71, realised 4.48 (over-projection 1.23)
```

**How to read this (§B):**

- **`rmse` down is good.** This is the main accuracy number.
- **`bias` near 0 is good.**
- **`rho` up is good.** It measures whether the ranking of players is right, and the ranking is
  what the solver uses.
- **The top-15 line** shows the optimiser's curse. FPL's `ep_next` over-projects its own top 15 by
  3.6 points per player per GW. The shrunk blend cuts that to 1.2.

**Checkpoint:** your three tables match these to the second decimal place. Commit.

---

## Step 5 — Your team, rebuilt from public data

**Goal:** `fpl my-team` shows your 15 players with purchase and selling prices, your bank, your
free transfers and your chips. No login is needed.

`src/fpl/optimise/prices.py`

```python
"""FPL selling prices. All prices are in tenths of £1m (61 = £6.1m)."""

from __future__ import annotations


def selling_price(purchase_price: int, now_cost: int) -> int:
    """You keep half of any rise, rounded down to 0.1m; you take the whole of any fall."""
    profit = now_cost - purchase_price
    if profit > 0:
        return purchase_price + profit // 2
    return now_cost
```

`src/fpl/team_state.py`

```python
"""Rebuild your current squad, bank, free transfers and chips from public endpoints.

No login is needed. The picks for a GW become public once its deadline has passed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fpl.config import CURRENT_SEASON
from fpl.context import GwContext, load_context, next_gw
from fpl.fplapi import FplClient
from fpl.optimise.prices import selling_price

TRANSFER_CHIPS = {"wildcard", "freehit"}


@dataclass(frozen=True)
class SquadPlayer:
    element: int
    purchase_price: int
    selling_price: int


@dataclass(frozen=True)
class TeamState:
    entry_id: int
    team_name: str
    based_on_gw: int
    squad: tuple[SquadPlayer, ...]
    bank: int
    free_transfers: int
    chips_available: tuple[str, ...]
    chips_used: tuple[str, ...]

    @property
    def elements(self) -> list[int]:
        return [p.element for p in self.squad]

    def selling_prices(self) -> dict[int, int]:
        return {p.element: p.selling_price for p in self.squad}


def current_team(con, client: FplClient, entry_id: int) -> tuple[GwContext, TeamState]:
    """The context for the next GW and the squad you carry into it."""
    ctx = load_context(con, CURRENT_SEASON, next_gw(con))
    return ctx, reconstruct(client, entry_id, ctx.state, ctx.gw, client.bootstrap())


def reconstruct(client: FplClient, entry_id: int, players: pd.DataFrame, next_gw: int, boot: dict) -> TeamState:
    """Return the squad you will carry into `next_gw`.

    `players` must have element, now_cost and cost_change_start (the current snapshot).
    """
    entry = client.entry(entry_id)
    history = client.entry_history(entry_id)
    transfers = client.entry_transfers(entry_id)
    chips_by_gw = {c["event"]: c["name"] for c in history["chips"]}
    last_gw = max(row["event"] for row in history["current"])

    # After a Free Hit, the picks for that GW are the Free Hit squad; the real squad reverted.
    base_gw = last_gw - 1 if chips_by_gw.get(last_gw) == "freehit" else last_gw
    squad = [pick["element"] for pick in client.entry_picks(entry_id, base_gw)["picks"]]

    applied = [
        t for t in sorted(transfers, key=lambda t: t["time"])
        if t["event"] > base_gw and chips_by_gw.get(t["event"]) != "freehit"
    ]
    for t in applied:
        squad[squad.index(t["element_out"])] = t["element_in"]

    bank_row = next(row for row in history["current"] if row["event"] == base_gw)
    bank = bank_row["bank"] + sum(t["element_out_cost"] - t["element_in_cost"] for t in applied)

    prices = players.set_index("element")
    purchase = _purchase_prices(client, squad, transfers, chips_by_gw, prices, entry["started_event"])
    members = tuple(
        SquadPlayer(e, purchase[e], selling_price(purchase[e], int(prices.at[e, "now_cost"]))) for e in squad
    )

    max_free = 1 + boot["game_config"]["rules"]["max_extra_free_transfers"]
    free = free_transfers(history["current"], chips_by_gw, entry["started_event"], max_free) - len(applied)

    return TeamState(
        entry_id=entry_id,
        team_name=entry["name"],
        based_on_gw=base_gw,
        squad=members,
        bank=bank,
        free_transfers=max(free, 0),
        chips_available=chips_available(boot["chips"], chips_by_gw, next_gw),
        chips_used=tuple(f"{name} (GW{gw})" for gw, name in sorted(chips_by_gw.items())),
    )


def free_transfers(current: list[dict], chips_by_gw: dict[int, str], started_event: int, max_free: int) -> int:
    """Free transfers available for the GW after the last finished one.

    Normal week: unused transfers roll over (+1 a week, capped). A hit leaves you with 1.
    Wildcard or Free Hit week: saved transfers are kept, with no +1 (FPL rules text).
    """
    free = 1  # the first GW after you join
    for row in sorted(current, key=lambda r: r["event"]):
        if row["event"] <= started_event:
            continue
        if chips_by_gw.get(row["event"]) in TRANSFER_CHIPS:
            continue
        free = min(max_free, max(free - row["event_transfers"], 0) + 1)
    return free


def chips_available(chip_windows: list[dict], chips_by_gw: dict[int, str], next_gw: int) -> tuple[str, ...]:
    """Chips you can play in `next_gw`, with the GW they expire."""
    available = []
    for chip in chip_windows:
        window = range(chip["start_event"], chip["stop_event"] + 1)
        used = any(name == chip["name"] and gw in window for gw, name in chips_by_gw.items())
        if next_gw in window and not used:
            available.append(f"{chip['name']} (until GW{chip['stop_event']})")
    return tuple(available)


def _purchase_prices(client, squad, transfers, chips_by_gw, prices, started_event) -> dict[int, int]:
    bought = {}
    for t in sorted(transfers, key=lambda t: t["time"]):
        if chips_by_gw.get(t["event"]) != "freehit":
            bought[t["element_in"]] = t["element_in_cost"]
    result = {}
    for element in squad:
        if element in bought:
            result[element] = bought[element]
        elif started_event == 1:  # prices do not change before the GW1 deadline
            result[element] = int(prices.at[element, "now_cost"] - prices.at[element, "cost_change_start"])
        else:  # joined later: the price in the round you joined
            rounds = client.element_summary(element)["history"]
            result[element] = next(r["value"] for r in rounds if r["round"] >= started_event)
    return result
```

Three rules from §E are coded here:

- After a Free Hit, the picks for that GW are not your squad.
- A player held since GW1 was bought at `now_cost − cost_change_start`.
- A Wildcard or Free Hit week keeps your saved transfers, with no +1.

`tests/test_prices_and_transfers.py`

```python
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
    assert free_transfers(_weeks(0, 0, 0), {}, started_event=1, max_free=5) == 3
    assert free_transfers(_weeks(0, 0, 0, 0, 0, 0, 0, 0), {}, started_event=1, max_free=5) == 5


def test_a_hit_leaves_one_free_transfer():
    assert free_transfers(_weeks(0, 3), {}, started_event=1, max_free=5) == 1


def test_wildcard_week_keeps_saved_transfers_without_the_plus_one():
    # GW2 +0 -> 2 for GW3; wildcard in GW3 keeps 2 for GW4
    assert free_transfers(_weeks(0, 0, 9), {3: "wildcard"}, started_event=1, max_free=5) == 2


def test_the_example_team():
    # Entry 1234567 in 2026/27: no transfers in GW2-3, two in GW4, two in GW5 -> 1 for GW6
    assert free_transfers(_weeks(0, 0, 0, 2, 2), {}, started_event=1, max_free=5) == 1
```

Add to `cli.py`, above `# --- Entry point`:

```python
# --- Step 5: your team ---------------------------------------------------------------

@command("my-team", "Show your squad, bank, free transfers and chips as the solver sees them")
def cmd_my_team(settings: Settings, args) -> None:
    from fpl.team_state import current_team

    with open_db(settings) as con:
        ctx, team = current_team(con, FplClient(settings), entry_id(settings))
    report.print_team(team, ctx)
```

Add to the end of `report.py`:

```python
# --- Step 5: your team ---------------------------------------------------------------

def names(ctx) -> pd.DataFrame:
    """Player names, positions and club short names, indexed by element id."""
    short = ctx.teams.set_index("team_id").short_name
    frame = ctx.state.set_index("element")[["web_name", "position", "team", "now_cost", "status", "news"]].copy()
    frame["club"] = frame.team.map(short)
    return frame


def print_team(team, ctx) -> None:
    who = names(ctx)
    print(f"{team.team_name} (entry {team.entry_id}), squad after GW{team.based_on_gw}, for GW{ctx.gw}")
    print(f"Bank {money(team.bank)} | Free transfers {team.free_transfers}")
    print(f"Chips available: {', '.join(team.chips_available) or 'none'}")
    if team.chips_used:
        print(f"Chips used: {', '.join(team.chips_used)}")
    rows = []
    for p in team.squad:
        n = who.loc[p.element]
        rows.append({"player": n.web_name, "pos": n.position, "club": n.club, "bought": money(p.purchase_price),
                     "now": money(n.now_cost), "sell": money(p.selling_price), "status": n.status,
                     "news": (n.news or "")[:40]})
    print(table(pd.DataFrame(rows).sort_values("pos", key=lambda s: s.map(POSITION_ORDER))))
```

**Run:**

```bash
fpl my-team
python -m pytest -q tests/test_prices_and_transfers.py
```

**Expected output:**

```text
Private Team (entry 1234567), squad after GW5, for GW6
Bank £1.0m | Free transfers 1
Chips available: wildcard (until GW19), freehit (until GW19), bboost (until GW19), 3xc (until GW19)
       player pos club bought    now   sell status                                     news
   Verbruggen GKP  BHA  £4.5m  £4.5m  £4.5m      a
     Dubravka GKP  TOT  £4.0m  £4.0m  £4.0m      a
    Calafiori DEF  ARS  £5.8m  £5.8m  £5.8m      a
     Gvardiol DEF  MCI  £5.5m  £5.7m  £5.6m      a
     Mitchell DEF  CRY  £4.5m  £4.5m  £4.5m      a
        Davis DEF  IPS  £4.0m  £4.0m  £4.0m      a
    van Ewijk DEF  COV  £4.0m  £4.0m  £4.0m      d Hamstring injury - 75% chance of playing
     Ødegaard MID  ARS  £6.7m  £6.8m  £6.7m      a
  B.Fernandes MID  MUN £12.0m £11.9m £11.9m      a
       Rogers MID  CHE  £7.7m  £7.7m  £7.7m      a
       Slater MID  HUL  £4.5m  £4.5m  £4.5m      a
       Tzolis MID  ARS  £6.5m  £6.3m  £6.3m      a
Calvert-Lewin FWD  LEE  £6.0m  £6.0m  £6.0m      a
      Haaland FWD  MCI £15.5m £15.6m £15.5m      a
   João Pedro FWD  CHE  £7.5m  £7.7m  £7.6m      d      Knee injury - 75% chance of playing
```

```text
......                                                                   [100%]
6 passed in 0.33s
```

Check this against the FPL website once. Look at the **Transfers** page for bank and free
transfers, and hover over a player to see his selling price. For your team, the free-transfer count
works out like this:

| GW  | Transfers made | Free transfers for the next GW |
| --- | -------------- | ------------------------------ |
| 2   | 0              | 2                              |
| 3   | 0              | 3                              |
| 4   | 2              | 2 (3 − 2 + 1)                  |
| 5   | 2              | **1** (2 − 2 + 1)              |

**Checkpoint:** the squad, bank (£1.0m) and free transfers (1) match the website. Commit.

---

## Step 6 — The solver and your first recommendation

**Goal:** `fpl recommend` gives the best transfer, the XI, the captain and the bench for GW6, and
says whether the transfer is worth making.

`src/fpl/projections/horizon.py`

```python
"""Turn a one-GW projection into a table of expected points for several GWs."""

from __future__ import annotations

import pandas as pd

from fpl.context import GwContext
from fpl.projections.baseline import Projector


def fixture_counts(fixtures: pd.DataFrame, gws: list[int]) -> pd.DataFrame:
    """Number of fixtures per team per GW (0 = blank, 2 = double)."""
    rows = []
    for side in ("team_h", "team_a"):
        part = fixtures[fixtures.gw.isin(gws)][["gw", side]].rename(columns={side: "team"})
        rows.append(part)
    counts = pd.concat(rows).value_counts().rename("n").reset_index()
    grid = pd.MultiIndex.from_product([sorted(set(fixtures.team_h)), gws], names=["team", "gw"])
    return counts.set_index(["team", "gw"]).reindex(grid, fill_value=0).n.unstack("gw")


def horizon_table(ctx: GwContext, projector: Projector, gws: list[int]) -> pd.DataFrame:
    """Players × GWs of expected points: per fixture if the model can, else repeated."""
    if hasattr(projector, "horizon"):
        return projector.horizon(ctx, gws)
    return repeat_over_horizon(ctx, projector, gws)


def repeat_over_horizon(ctx: GwContext, projector: Projector, gws: list[int]) -> pd.DataFrame:
    """Expected points per player (rows) per GW (columns): the one-GW value × fixture count.

    This is what the skeleton does: it has no view of future opponents. The full model in
    part 2 projects each fixture instead.
    """
    per_gw = projector(ctx)
    counts = fixture_counts(ctx.fixtures, gws)
    team = ctx.state.set_index("element").team
    table = counts.reindex(team.to_numpy()).set_axis(team.index, axis=0)
    return table.mul(per_gw.reindex(team.index), axis=0).fillna(0.0)
```

`src/fpl/optimise/solver.py`

```python
"""Multi-GW transfer optimiser: a mixed-integer linear program (MILP).

Decision per player p and GW g: in the squad (x), in the XI (y), captain (c), bought, sold.
Constraints: squad rules, club limit, budget with selling prices, free-transfer rollover.
Objective: discounted expected points of XI + captain, a little for the bench, minus hits.
See 01-reference.md H.9 for the free-transfer constraints.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import pulp

from fpl.team_state import TeamState

SQUAD_QUOTA = {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
XI_RANGE = {"GKP": (1, 1), "DEF": (3, 5), "MID": (2, 5), "FWD": (1, 3)}
CLUB_LIMIT = 3


@dataclass(frozen=True)
class SolverSettings:
    bench_weight: float = 0.15     # bench points only count through autosubs
    decay: float = 0.9             # a point next week is worth less than a point this week
    hit_cost: int = 4
    max_hits_per_gw: int = 0       # 0 = never take a hit; raise it with --max-hits
    max_free_transfers: int = 5
    free_transfer_bonus: float = 0.01  # makes the reported free-transfer count exact (H.9)
    allow_transfers: bool = True
    hold_first_gw: bool = False    # no transfers in the first GW, later ones allowed ("roll")
    candidates_per_position: int = 50  # plus your own players; keeps the problem small
    time_limit_s: int = 60


@dataclass
class GwPlan:
    gw: int
    buy: list[int]
    sell: list[int]
    xi: list[int]
    bench: list[int]            # in autosub order; the reserve goalkeeper is always first
    captain: int
    vice: int
    free_transfers: int
    hits: int
    expected_points: float      # XI + captain, no bench


@dataclass
class Plan:
    objective: float
    gws: list[GwPlan] = field(default_factory=list)


def optimise(ep: pd.DataFrame, players: pd.DataFrame, team: TeamState, settings: SolverSettings = SolverSettings()) -> Plan:
    """Best plan over the GWs in `ep` (players × GW columns of expected points).

    `players` needs element, position, team, now_cost (and optionally loan_ineligible_gws).
    """
    gws = list(ep.columns)
    info = players.set_index("element")
    pool = _candidate_pool(ep, info, team, settings)
    ep = ep.reindex(pool).fillna(0.0).clip(lower=0.0)
    info = info.loc[pool]
    owned = set(team.elements)
    sell_value = {p: team.selling_prices().get(p, int(info.at[p, "now_cost"])) for p in pool}

    model = pulp.LpProblem("fpl", pulp.LpMaximize)
    per_player = lambda name: model.add_variable_dicts(
        name, (pool, gws), lowBound=0, upBound=1, cat="Binary"
    )
    per_gw = lambda name, **kwargs: model.add_variable_dicts(name, gws, **kwargs)
    x, y, c, buy, sell = (per_player(n) for n in ("squad", "xi", "captain", "buy", "sell"))
    free = per_gw("free", lowBound=0, upBound=settings.max_free_transfers, cat="Integer")
    carry = per_gw("carry", lowBound=0, upBound=settings.max_free_transfers, cat="Integer")
    has_carry = per_gw("has_carry", cat="Binary")
    hits = per_gw("hits", lowBound=0, cat="Integer")
    bank = per_gw("bank", lowBound=0)
    big_m = 20

    for i, g in enumerate(gws):
        previous = (lambda p: 1 if p in owned else 0) if i == 0 else (lambda p, g0=gws[i - 1]: x[p][g0])
        previous_bank = team.bank if i == 0 else bank[gws[i - 1]]
        used = pulp.lpSum(buy[p][g] for p in pool)

        # Squad and XI rules
        model += pulp.lpSum(x[p][g] for p in pool) == 15
        model += pulp.lpSum(y[p][g] for p in pool) == 11
        model += pulp.lpSum(c[p][g] for p in pool) == 1
        for position, quota in SQUAD_QUOTA.items():
            members = [p for p in pool if info.at[p, "position"] == position]
            low, high = XI_RANGE[position]
            model += pulp.lpSum(x[p][g] for p in members) == quota
            model += pulp.lpSum(y[p][g] for p in members) >= low
            model += pulp.lpSum(y[p][g] for p in members) <= high
        for club in info.team.unique():
            model += pulp.lpSum(x[p][g] for p in pool if info.at[p, "team"] == club) <= CLUB_LIMIT
        for p in pool:
            model += y[p][g] <= x[p][g]
            model += c[p][g] <= y[p][g]
            model += x[p][g] == previous(p) + buy[p][g] - sell[p][g]
            model += buy[p][g] + sell[p][g] <= 1
            if g in _ineligible_gws(info, p):
                model += y[p][g] == 0
            if not settings.allow_transfers or (settings.hold_first_gw and i == 0):
                model += buy[p][g] == 0

        # Budget: selling price for players you own now, current price otherwise
        model += bank[g] == previous_bank + pulp.lpSum(
            sell_value[p] * sell[p][g] - int(info.at[p, "now_cost"]) * buy[p][g] for p in pool
        )

        # Free transfers (H.9): hits for transfers beyond the free ones, then roll over
        if i == 0:
            model += free[g] == team.free_transfers
        model += hits[g] >= used - free[g]
        model += hits[g] <= settings.max_hits_per_gw
        model += carry[g] <= free[g] - used + big_m * (1 - has_carry[g])
        model += carry[g] <= big_m * has_carry[g]
        if i + 1 < len(gws):
            model += free[gws[i + 1]] <= carry[g] + 1

    weight = {g: settings.decay**i for i, g in enumerate(gws)}
    points = pulp.lpSum(
        weight[g] * float(ep.at[p, g]) * (y[p][g] + c[p][g] + settings.bench_weight * (x[p][g] - y[p][g]))
        for p in pool for g in gws
    )
    penalties = pulp.lpSum(weight[g] * settings.hit_cost * hits[g] for g in gws)
    model += points - penalties + settings.free_transfer_bonus * pulp.lpSum(free[g] for g in gws)

    solve_stats = model.solve(_solver(settings))
    if solve_stats.status != pulp.LpSolveStatus.Optimal:
        raise RuntimeError(f"Solver finished with status {solve_stats.status_str}")

    plan = Plan(objective=float(pulp.value(points - penalties)))
    for g in gws:
        chosen = lambda var: [p for p in pool if var[p][g].value() > 0.5]
        xi = chosen(y)
        captain = chosen(c)[0]
        bench = [p for p in chosen(x) if p not in xi]
        plan.gws.append(
            GwPlan(
                gw=g,
                buy=chosen(buy),
                sell=chosen(sell),
                xi=sorted(xi, key=lambda p: (list(SQUAD_QUOTA).index(info.at[p, "position"]), -ep.at[p, g])),
                bench=_bench_order(bench, ep[g], info),
                captain=captain,
                vice=max((p for p in xi if p != captain), key=lambda p: ep.at[p, g]),
                free_transfers=round(free[g].value()),
                hits=round(hits[g].value()),
                expected_points=float(sum(ep.at[p, g] for p in xi) + ep.at[captain, g]),
            )
        )
    return plan


def _candidate_pool(ep: pd.DataFrame, info: pd.DataFrame, team: TeamState, settings: SolverSettings) -> list[int]:
    """Your players plus the best N per position by total expected points."""
    total = ep.sum(axis=1).rename("total").to_frame().join(info.position)
    best = total.sort_values("total", ascending=False).groupby("position").head(settings.candidates_per_position)
    return sorted(set(best.index) | set(team.elements))


def _bench_order(bench: list[int], ep: pd.Series, info: pd.DataFrame) -> list[int]:
    goalkeeper = [p for p in bench if info.at[p, "position"] == "GKP"]
    outfield = sorted((p for p in bench if p not in goalkeeper), key=lambda p: -ep[p])
    return goalkeeper + outfield


def _ineligible_gws(info: pd.DataFrame, p: int) -> set[int]:
    if "loan_ineligible_gws" not in info.columns:
        return set()
    text = info.at[p, "loan_ineligible_gws"]
    return {int(g) for g in str(text).split(",") if g.strip().isdigit()}


def _solver(settings: SolverSettings):
    if "HiGHS" in pulp.listSolvers(onlyAvailable=True):
        return pulp.HiGHS(msg=False, timeLimit=settings.time_limit_s)
    return pulp.PULP_CBC_CMD(msg=False, timeLimit=settings.time_limit_s)
```

The solver is a MILP (§H.6), built with PuLP and solved by HiGHS. Read `optimise()` from top to
bottom. Each block of constraints matches one FPL rule, and the objective is the last statement
before `model.solve`. The free-transfer constraints are H.9.

`src/fpl/recommend.py`

```python
"""Put the pieces together: projections for the next GWs, your squad, and the solver."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from fpl.config import CURRENT_SEASON
from fpl.context import GwContext
from fpl.fplapi import FplClient
from fpl.optimise.solver import Plan, SolverSettings, optimise
from fpl.projections import registry
from fpl.projections.horizon import horizon_table
from fpl.team_state import TeamState, current_team


@dataclass
class Recommendation:
    ctx: GwContext
    team: TeamState
    ep: pd.DataFrame
    plan: Plan          # transfers allowed in every GW
    hold: Plan          # no transfer this GW (roll it), transfers allowed later
    threshold: float

    @property
    def gain(self) -> float:
        return self.plan.objective - self.hold.objective

    @property
    def make_transfers(self) -> bool:
        first = self.plan.gws[0]
        return bool(first.buy) and self.gain >= self.threshold

    @property
    def chosen(self) -> Plan:
        return self.plan if self.make_transfers else self.hold


def recommend(con, client: FplClient, entry_id: int, model: str = "shrunk_blend", horizon: int = 4,
              threshold: float = 2.0, settings: SolverSettings = SolverSettings()) -> Recommendation:
    ctx, team = current_team(con, client, entry_id)
    gws = [g for g in range(ctx.gw, ctx.gw + horizon) if g <= 38]
    ep = horizon_table(ctx, registry.build(model, con, CURRENT_SEASON, first_gw=ctx.gw), gws)
    plan = optimise(ep, ctx.state, team, settings)
    hold = optimise(ep, ctx.state, team, replace(settings, hold_first_gw=True))
    return Recommendation(ctx, team, ep, plan, hold, threshold)
```

`recommend()` solves twice:

- once with transfers allowed;
- once with **no transfer this GW** (roll the free transfer), with transfers allowed later.

The difference between the two is the value of transferring now rather than banking the transfer.
A transfer is recommended only if that gain is at least `--threshold` points (default 2).

`tests/test_solver.py`

```python
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
            rows.append({"element": element, "position": position, "team": element, "now_cost": 50})
            element += 1
    for position in ["MID", "MID", "FWD", "DEF"]:
        rows.append({"element": element, "position": position, "team": 99, "now_cost": 50})
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
```

Add to `cli.py`, above `# --- Entry point`:

```python
# --- Step 6: recommendation ----------------------------------------------------------

@command("recommend", "Recommend transfers, XI and captain for the next GW",
         arg("--model", default="shrunk_blend"), arg("--horizon", type=int, default=4),
         arg("--threshold", type=float, default=2.0, help="minimum gain over rolling, in points"),
         arg("--max-hits", type=int, default=0, help="hits allowed per GW (default 0)"),
         arg("--save", action="store_true", help="record the run, to settle after the GW (step 7)"))
def cmd_recommend(settings: Settings, args) -> None:
    from fpl.optimise.solver import SolverSettings
    from fpl.recommend import recommend

    solver = SolverSettings(max_hits_per_gw=args.max_hits)
    with open_db(settings) as con:
        result = recommend(con, FplClient(settings), entry_id(settings), args.model, args.horizon,
                           args.threshold, solver)
        if args.save:
            from fpl.runs import save_run

            print(f"Saved as run {save_run(con, result, args.model)}.\n")
    report.print_recommendation(result)
```

Add to the end of `report.py`:

```python
# --- Step 6: recommendation ----------------------------------------------------------

def print_recommendation(result) -> None:
    who = names(result.ctx)
    label = lambda p: f"{who.at[p, 'web_name']} ({who.at[p, 'club']})"
    first = result.plan.gws[0]
    horizon = f"GW{result.plan.gws[0].gw}-{result.plan.gws[-1].gw}"
    print(f"{result.team.team_name}: GW{result.ctx.gw} recommendation, horizon {horizon}")
    print(f"Bank {money(result.team.bank)} | Free transfers {result.team.free_transfers}")
    print()
    if first.buy:
        ep_now = result.ep[first.gw]
        for out, into in zip(first.sell, first.buy):
            print(f"  Best transfer: OUT {label(out)} {money(result.team.selling_prices()[out])} (EP {ep_now[out]:.2f})"
                  f"  ->  IN {label(into)} {money(who.at[into, 'now_cost'])} (EP {ep_now[into]:.2f})")
        print(f"  Hits: {first.hits}. Gain over rolling the transfer, across {horizon}: {result.gain:+.2f} points "
              f"(threshold {result.threshold:.1f})")
        verdict = "MAKE the transfer(s)." if result.make_transfers else "gain below threshold: HOLD (roll the transfer)."
        print(f"  Verdict: {verdict}")
    else:
        print("  No transfer improves the plan. HOLD.")
    chosen = result.chosen.gws[0]
    ep = result.ep[chosen.gw]
    print()
    print(f"Starting XI for GW{chosen.gw} (expected points incl. captain: {chosen.expected_points:.1f})")
    for p in chosen.xi:
        tag = " (C)" if p == chosen.captain else " (V)" if p == chosen.vice else ""
        print(f"  {who.at[p, 'position']}  {label(p):<28} {ep[p]:5.2f}{tag}")
    print("Bench, in order: " + ", ".join(f"{label(p)} {ep[p]:.2f}" for p in chosen.bench))
    later = [g for g in result.plan.gws[1:] if g.buy]
    if later:
        print()
        print("Planned later (not an action now): " + "; ".join(
            f"GW{g.gw}: " + ", ".join(f"{who.at[o, 'web_name']} -> {who.at[i, 'web_name']}"
                                      for o, i in zip(g.sell, g.buy)) for g in later))
```

**Run:**

```bash
python -m pytest -q tests/test_solver.py
fpl recommend
```

**Expected output:**

```text
...                                                                      [100%]
3 passed in 0.51s
```

```text
Private Team: GW6 recommendation, horizon GW6-9
Bank £1.0m | Free transfers 1

  Best transfer: OUT Tzolis (ARS) £6.3m (EP 2.86)  ->  IN Groß (BHA) £5.8m (EP 7.00)
  Hits: 0. Gain over rolling the transfer, across GW6-9: +4.69 points (threshold 2.0)
  Verdict: MAKE the transfer(s).

Starting XI for GW6 (expected points incl. captain: 60.0)
  GKP  Verbruggen (BHA)              4.08
  DEF  Gvardiol (MCI)                5.40
  DEF  Calafiori (ARS)               4.40
  DEF  Davis (IPS)                   4.40
  DEF  Mitchell (CRY)                4.35
  MID  Groß (BHA)                    7.00 (C)
  MID  B.Fernandes (MUN)             5.00
  MID  Rogers (CHE)                  4.33
  MID  Ødegaard (ARS)                4.14
  FWD  Haaland (MCI)                 5.98 (V)
  FWD  Calvert-Lewin (LEE)           3.92
Bench, in order: Dubravka (TOT) 0.00, João Pedro (CHE) 3.41, Slater (HUL) 2.72, van Ewijk (COV) 1.45

Planned later (not an action now): GW7: van Ewijk -> Bogle; GW8: Calafiori -> Tarkowski; GW9: Ødegaard -> Schade
```

**What the three safety settings do.** Try this:

```bash
fpl recommend --model blend --max-hits 5
```

```text
Private Team: GW6 recommendation, horizon GW6-9
Bank £1.0m | Free transfers 1

  Best transfer: OUT Calafiori (ARS) £5.8m (EP 5.40)  ->  IN Schade (BRE) £6.2m (EP 8.40)
  Best transfer: OUT Ødegaard (ARS) £6.7m (EP 5.15)  ->  IN Groß (BHA) £5.8m (EP 10.30)
  Best transfer: OUT van Ewijk (COV) £4.0m (EP 1.01)  ->  IN Tarkowski (EVE) £6.1m (EP 8.90)
  Best transfer: OUT Mitchell (CRY) £4.5m (EP 5.30)  ->  IN Bogle (LEE) £4.6m (EP 8.70)
  Best transfer: OUT Dubravka (TOT) £4.0m (EP 0.00)  ->  IN Tzolakis (HUL) £4.7m (EP 6.40)
  Best transfer: OUT Tzolis (ARS) £6.3m (EP 2.85)  ->  IN Maitland-Niles (EVE) £4.5m (EP 7.00)
  Hits: 5. Gain over rolling the transfer, across GW6-9: +20.07 points (threshold 2.0)
```

The unshrunk blend with hits allowed recommends six transfers and five hits, for a "gain" of +20
points. That is the optimiser's curse on noisy early-season numbers. Three settings protect you:

- the shrunk projection
- no hits by default
- the threshold against rolling

**Checkpoint:** a legal recommendation for your team. The walking skeleton is complete: from here
on, every improvement is measured against this. Commit.

---

## Step 7 — Record each recommendation and settle it after the GW

**Goal:** `fpl recommend --save` stores two plans: the one recommended, and the "roll" plan.
`fpl settle` fills in their real points after the GW. Over the season this tells you whether
acting on the recommendations helped. It compares the two plans for the same GW (§B).

`src/fpl/runs.py`

```python
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
    projections = result.ep[[result.ctx.gw]].rename(columns={result.ctx.gw: "ep"}).rename_axis("element").reset_index()
    replace_rows(con, "run_projections", projections.assign(run_id=run_id, gw=result.ctx.gw), run_id=run_id)
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
        realised = lambda xi, captain: float(points.reindex(json.loads(xi)).fillna(0).sum() + points.get(captain, 0))
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
```

`tests/test_runs.py`

```python
import json

import duckdb
import pandas as pd

from fpl.runs import settle


def test_settle_fills_realised_points_for_both_plans():
    con = duckdb.connect()
    con.execute("create table events as select '2026-27' as season, 6 as gw, true as finished")
    points = pd.DataFrame({"season": "2026-27", "gw": 6, "element": [1, 2, 3], "total_points": [2.0, 6.0, 9.0]})
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
    realised, hold = con.execute("select realised_points, hold_realised_points from runs").fetchone()
    assert realised == 2 + 6 + 6      # captain counts twice
    assert hold == 2 + 9 + 9
```

Add to `cli.py`, above `# --- Entry point`:

```python
# --- Step 7: record and settle ------------------------------------------------------

@command("settle", "Fill in realised points for saved runs whose GW has finished")
def cmd_settle(settings: Settings, args) -> None:
    from fpl.runs import run_history, settle

    with open_db(settings) as con:
        settled = settle(con)
        report.print_runs(settled, run_history(con))
```

Add to the end of `report.py`:

```python
# --- Step 7: record and settle ------------------------------------------------------

def print_runs(settled: int, history: pd.DataFrame) -> None:
    print(f"Settled {settled} run(s).")
    if history.empty:
        print("No saved runs yet. Save one with: fpl recommend --save")
    else:
        print(table(history))
```

**Run:**

```bash
python -m pytest -q tests/test_runs.py
fpl recommend --save
fpl settle
```

**Expected output** (the first lines of `recommend --save`, then `settle`):

```text
Saved as run cb1e51086e0e.
```

```text
Settled 0 run(s).
 gw                       created_at        model  made_transfers gain expected realised hold_expected hold_realised
  6 2026-09-26 21:12:53.717155+02:00 shrunk_blend            True 4.69    60.00      NaN         55.40           NaN
```

`realised` stays empty until GW6 finishes. On Tuesday 13 October, after 08:00 UTC, run
`fpl update && fpl settle` to fill it in.

**Checkpoint:** all tests pass (`python -m pytest -q` → 15 passed). **Part 1 is done:** you
can make a defensible GW6 decision today. Commit, then continue with **03-build-part2.md**.
