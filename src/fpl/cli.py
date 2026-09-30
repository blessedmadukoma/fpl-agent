"""Command-line entrypoint: `fpl <command>` (or `python -m fpl <command>`).

Each command is a small function: open resources, call one piece of the library, print.
"""

from __future__ import annotations

import argparse
import logging
import platform
from importlib.metadata import version

from fpl import report
from fpl.config import Settings, load_settings
from fpl.fplapi import FplClient

COMMANDS: dict[str, tuple] = {}


def command(name: str, help_text: str, *arguments):
    """Register a function as a sub-command. `arguments` are arg(...) values"""
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


@command("doctor", "Check the Python environment, the API and your settings")
def cmd_doctor(settings: Settings, args) -> None:
    print(f"Python       {platform.python_version()}")
    for package in ["httpx", "duckdb", "pandas", "numpy", "scipy", "scikit-learn", "pulp", "highspy"]:
        print(f"{package:<12} {version(package)}")
    boot = FplClient(settings, save_raw=False).bootstrap()
    next_event = next(e for e in boot["events"] if not e["finished"])
    print(f"FPL API      ok: {len(boot['elements'])} players, next deadline GW{next_event['id']} "
          f"{next_event['deadline_time']}")
    print(
        f"Entry ID     {settings.entry_id or 'NOT SET: add FPL_ENTRY_ID to .env'}")
    print(f"Data folder  {settings.data_dir}")


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


@command("check-scoring", "Recompute every player's points and compare with FPL",
         arg("--season", default="2026-27"))
def cmd_check_scoring(settings: Settings, args) -> None:
    from fpl.checks import check_scoring

    with open_db(settings) as con:
        result = check_scoring(con, args.season)
    report.print_scoring_check(result)


@command("load-history", "Download last season and the pre-deadline snapshots (under a minute)")
def cmd_load_history(settings: Settings, args) -> None:
    from fpl.ingest.history import load_states_from_fplcache, load_vaastav_season

    with open_db(settings) as con:
        past = load_states_from_fplcache(
            settings, con, settings.history_season)
        now = load_states_from_fplcache(
            settings, con, settings.current_season, with_metadata=False)

        results = load_vaastav_season(settings, con, settings.history_season)
    report.print_history_load(past, now, results)


@command("backtest", "Score a projection model on a past season",
         arg("--model", default="shrunk_blend"), arg("--season",
                                                     default=Settings.history_season),
         arg("--from-gw", type=int, default=5), arg("--to-gw", type=int, default=38))
def cmd_backtest(settings: Settings, args) -> None:
    from fpl.backtest.replay import replay, summarise
    from fpl.projections import registry

    with open_db(settings) as con:
        projector = registry.build(
            args.model, con, args.season, first_gw=args.from_gw)
        frame = replay(con, args.season, projector,
                       range(args.from_gw, args.to_gw + 1))
    report.print_backtest(args.model, args.season,
                          args.from_gw, args.to_gw, *summarise(frame))


@command("my-team", "Show my squad, bank, free transfers and chips as the solver sees them")
def cmd_my_team(settings: Settings, args) -> None:
    from fpl.team_state import current_team

    with open_db(settings) as con:
        ctx, team = current_team(con, FplClient(settings), entry_id(settings))
    report.print_team(team, ctx)


@command("recommend", "Recommend transfers, XI and captain for the next GW",
         arg("--model", default="shrunk_blend"), arg("--horizon", type=int, default=4),
         arg("--threshold", type=float, default=2.0,
             help="minimum gain over rolling, in points"),
         arg("--max-hits", type=int, default=0,
             help="hits allowed per GW (default 0)"),
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


@command("settle", "Fill in realised points for saved runs whose GW has finished")
def cmd_settle(settings: Settings, args) -> None:
    from fpl.runs import run_history, settle

    with open_db(settings) as con:
        settled = settle(con)
        report.print_runs(settled, run_history(con))


@command("odds", "Download bookmaker odds and turn them into expected goals per fixture")
def cmd_odds(settings: Settings, args) -> None:
    from fpl.ingest.odds import load_odds

    with open_db(settings) as con:
        for season in (Settings.history_season, Settings.current_season):
            report.print_odds_load(load_odds(settings, con, season))


@command("fixtures", "Clean-sheet chance per team for the next GWs", arg("--gws", type=int, default=6))
def cmd_fixtures(settings: Settings, args) -> None:
    from fpl.context import load_context, next_gw
    from fpl.projections.teams import fixture_rates, team_view

    with open_db(settings) as con:
        ctx = load_context(con, Settings.current_season, next_gw(con))
        view = team_view(fixture_rates(
            con, ctx, list(range(ctx.gw, ctx.gw + args.gws))))
    report.print_fixture_ticker(view, ctx)


@command("backtest-teams", "Score clean-sheet probabilities on a past season",
         arg("--season", default=Settings.history_season))
def cmd_backtest_teams(settings: Settings, args) -> None:
    from fpl.backtest.teams import clean_sheet_backtest

    with open_db(settings) as con:
        print(report.table(clean_sheet_backtest(
            con, args.season, range(5, 39)), "{:.4f}"))


@command("backtest-minutes", "Score the minutes model on GW20-38 after training on GW2-19",
         arg("--season", default=Settings.history_season))
def cmd_backtest_minutes(settings: Settings, args) -> None:
    from fpl.backtest.minutes import minutes_backtest

    with open_db(settings) as con:
        print(report.table(minutes_backtest(con, args.season), "{:.4f}"))


@command("projections", "Top players for the next GW with every points component",
         arg("--top", type=int, default=25), arg("--position", help="GKP, DEF, MID or FWD"))
def cmd_projections(settings: Settings, args) -> None:
    from fpl.context import load_context, next_gw
    from fpl.projections import registry

    with open_db(settings) as con:
        ctx = load_context(con, Settings.current_season, next_gw(con))
        rows = registry.build("full", con, Settings.current_season,
                              first_gw=ctx.gw).project(ctx, [ctx.gw])
    report.print_projections(rows, ctx, args.top, args.position)


@command("chips", "Value of Triple Captain, Bench Boost and Free Hit in each GW up to GW19",
         arg("--model", default="full"), arg("--to-gw", type=int, default=19))
def cmd_chips(settings: Settings, args) -> None:
    from fpl.optimise.chips import chip_values
    from fpl.projections import registry
    from fpl.projections.horizon import horizon_table
    from fpl.team_state import current_team

    with open_db(settings) as con:
        ctx, team = current_team(con, FplClient(settings), entry_id(settings))
        projector = registry.build(
            args.model, con, Settings.current_season, first_gw=ctx.gw)
        ep = horizon_table(ctx, projector, list(range(ctx.gw, args.to_gw + 1)))
    report.print_chips(chip_values(ep, ctx.state, team), team)


def main(argv: list[str] | None = None) -> None:
    """entry point"""
    logging.basicConfig(level=logging.INFO,
                        format="%(levelname)s %(name)s: %(message)s")
    # one line per request is too noisy
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(
        prog="fpl", description="FPL projections and optimiser")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (func, help_text, arguments) in COMMANDS.items():
        p = sub.add_parser(name, help=help_text)
        for flags, kwargs in arguments:
            p.add_argument(*flags, **kwargs)
        p.set_defaults(func=func)
    args = parser.parse_args(argv)
    args.func(load_settings(), args)
