"""Command-line entrypoint: `fpl <command>` (or `python -m fpl <command>`).

Each command is a small function: open resources, call one piece of the library, print.
"""

from __future__ import annotations

import argparse
import logging
import platform
import re
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

from fpl import report
from fpl.agent.model import SYSTEM_PROMPT_PATH, message_client
from fpl.agent.observability import build_run_metadata
from fpl.agent.service import tool_definitions
from fpl.config import Settings, load_settings
from fpl.evals.runner import load_cases, run_cases, save_results, score_results
from fpl.evals.snapshot import validate_snapshot
from fpl.evals.snapshot_files import calculate_file_sha256, read_manifest
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
    for package in ["httpx", "duckdb", "pandas", "numpy", "scipy", "scikit-learn", "pulp", "highspy", "openai", "pydantic", "langfuse"]:
        print(f"{package:<12} {version(package)}")
    boot = FplClient(settings, save_raw=False).bootstrap()
    next_event = next(e for e in boot["events"] if not e["finished"])
    print(f"FPL API      ok: {len(boot['elements'])} players, next deadline GW{next_event['id']} "
          f"{next_event['deadline_time']}")
    print(
        f"Entry ID     {settings.entry_id or 'NOT SET: add FPL_ENTRY_ID to .env'}")
    print(f"Data folder  {settings.data_dir}")
    print(
        f"Ollama URL and model configured: {'yes' if settings.ollama_base_url and settings.ollama_model else 'No'}")
    print(
        f"LangFuse URL and keys: {'yes' if settings.langfuse_base_url and settings.langfuse_public_key and settings.langfuse_secret_key  else 'No'}")


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


@command("freeze-eval", "Freeze current",
         arg("--name", default="pre-gw6-baseline"))
def cmd_create_snapshot(settings: Settings, args) -> None:
    from fpl.evals.snapshot import create_snapshot
    from fpl.ingest.current import update_current
    from fpl.team_state import current_team

    client = FplClient(settings)
    with open_db(settings) as con:
        update_summary = update_current(client, con)
        ctx, team = current_team(con, client, entry_id(settings))

    # create snapshot
    response = create_snapshot(
        ctx,
        settings,
        name=args.name,
        team=team,
        update_summary=update_summary,
        raw_paths=client.saved_raw_paths,
    )

    report.print_snapshot(response)


@command(
    "ask",
    "Answer an FPL question using a frozen snapshot",
    arg("question"),
    arg("--snapshot", type=Path, required=True),
    arg("--horizon", type=int, choices=range(1, 7),
        help="Application-selected planning horizon; overrides model arguments"),
)
def cmd_ask_model(settings: Settings, args):
    from fpl.agent.loop import agent_loop

    options = {} if args.horizon is None else {"horizon": args.horizon}
    answer = agent_loop(settings, args.question, args.snapshot, **options)
    # report.print_model_answer(answer)
    print(answer)


@command(
    "ask-current",
    "Refresh data, load missing history, freeze a snapshot and answer",
    arg("question"),
    arg("--name", default="ask-current", help="Human name for the new snapshot"),
    arg("--horizon", type=int, choices=range(1, 7),
        help="Application-selected planning horizon; overrides model arguments"),
)
def cmd_ask_current(settings: Settings, args) -> None:
    from fpl.agent.current import prepare_current_snapshot
    from fpl.agent.loop import agent_loop

    if not args.question.strip():
        raise SystemExit("Provide a non-empty question.")
    entry_id(settings)
    response = prepare_current_snapshot(settings, args.name)
    report.print_snapshot(response)
    options = {} if args.horizon is None else {"horizon": args.horizon}
    answer = agent_loop(
        settings, args.question, Path(response["final_path"]), **options,
    )
    print(answer)


@command(
    "eval",
    "Run fixed FPL agent evaluation cases",
    arg("--cases", type=Path, required=True),
    arg("--snapshot", type=Path, required=True),
    arg("--run-id", required=True),
)
def cmd_eval(settings: Settings, args):
    cases = load_cases(args.cases)
    snapshot = validate_snapshot(args.snapshot)

    if not cases:
        raise SystemExit("No evaluation cases found.")

    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id):
        raise SystemExit(
            "Invalid run name: use only letters, numbers, hyphens and underscores.")

    case_ids = [case["id"] for case in cases]
    duplicates = sorted({cid for cid in case_ids if case_ids.count(cid) > 1})
    if duplicates:
        raise SystemExit(f"Duplicate case IDs: {', '.join(duplicates)}")

    snapshot_id = snapshot["snapshot_id"]
    mismatched = [case["id"]
                  for case in cases if case["snapshot_id"] != snapshot_id]
    if mismatched:
        raise SystemExit(
            f"Cases with mismatched snapshot_id (expected {snapshot_id!r}): "
            f"{', '.join(mismatched)}")

    run_dir = settings.data_dir / "evals" / "runs"

    run_dir.mkdir(parents=True, exist_ok=True)

    raw_path = run_dir / f"{args.run_id}.jsonl"
    scored_path = run_dir / f"{args.run_id}-scored.jsonl"
    manifest_path = run_dir / f"{args.run_id}-manifest.jsonl"

    for path in (raw_path, scored_path, manifest_path):
        if path.exists():
            raise SystemExit(f"Refusing to overwrite existing file: {path}")

    local_prompt = message_client("")[0]["content"]

    manifest = read_manifest(args.snapshot)

    try:
        run_manifest = build_run_metadata(
            manifest=manifest,
            system_prompt=local_prompt,
            team_tools=tool_definitions(),
            session_id=args.run_id,
            run_id=args.run_id,
            model=settings.ollama_model,
            run_kind="evaluation",
        )
    except Exception as exc:
        raise SystemExit(
            f"Failed to build run metadata ({type(exc).__name__})."
        ) from None

    run_manifest.update({
        "dataset_file": args.cases.name,
        "dataset_hash": calculate_file_sha256(args.cases),
        "case_count": len(cases),
        "creation_time": datetime.now(timezone.utc).isoformat(),
        "model_endpoint": settings.ollama_base_url,
        "prompt_file": SYSTEM_PROMPT_PATH.name,
    })

    save_results([run_manifest], manifest_path)

    run_cases(settings, cases, raw_path,
              snapshot_root=args.snapshot.parent, run_id=args.run_id)

    records = load_cases(raw_path)
    scored = score_results(cases, records)
    save_results(scored, scored_path)

    print(f"Saved {len(records)} records.")
    print(f"Raw results:    {raw_path}")
    print(f"Scored results: {scored_path}")
    print(f"Manifest:       {manifest_path}")


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
