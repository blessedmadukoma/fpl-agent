"""Everything that prints. Library code returns data; this module turns it into text."""

from __future__ import annotations

import pandas as pd

POSITION_ORDER = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}


def table(df: pd.DataFrame, floatfmt: str = "{:.2f}") -> str:
    """Format a DataFrame for the terminal with consistent number formatting."""
    formatters = {
        c: floatfmt.format for c in df.columns if pd.api.types.is_float_dtype(df[c])}
    return df.to_string(index=False, formatters=formatters)


def money(tenths: float) -> str:
    return f"£{tenths / 10:.1f}m"


def print_update(summary: dict) -> None:
    print(f"Season {summary['season']}: {summary['players']} players")
    print(
        f"Finished GWs: {summary['finished_gws']} ({summary['player_gw_rows']} player-GW rows)")
    print(
        f"Next: GW{summary['next_gw']}, deadline {summary['next_deadline']:%a %d %b %Y %H:%M} UTC")


def print_scoring_check(result) -> None:
    print(f"Season {result.season}, source {result.source}: checked {result.checked:,} rows"
          + (f", skipped {result.skipped:,} double-GW rows" if result.skipped else ""))
    if result.mismatches.empty:
        print("0 mismatches. The scoring function matches FPL exactly.")
    else:
        print(f"{len(result.mismatches):,} MISMATCHES. First 20:")
        print(result.mismatches.head(20).to_string(index=False))


def print_history_load(past: dict, now: dict, results: dict) -> None:
    for s in (past, now):
        print(f"{s['season']}: {s['gws']} pre-deadline snapshots "
              f"(median {s['median_lead_h']:.1f} h before the deadline, max {s['max_lead_h']:.1f} h)")
    print(f"{results['season']} results: {results['player_fixture_rows']:,} player-fixture rows, "
          f"{results['player_gw_rows']:,} player-GW rows, {results['fixtures']} fixtures")


def print_backtest(model: str, season: str, first: int, last: int, metrics: pd.DataFrame, top: dict) -> None:
    print(f"Model '{model}', {season} GW{first}-{last}")
    print(table(metrics))
    print(f"Top {top['top_k']} per GW: projected {top['projected']:.2f}, realised {top['realised']:.2f} "
          f"(over-projection {top['projected'] - top['realised']:.2f})")


def names(ctx) -> pd.DataFrame:
    """Player names, positions and club short names, indexed by element id."""
    short = ctx.teams.set_index("team_id").short_name
    frame = ctx.state.set_index("element")[
        ["web_name", "position", "team", "now_cost", "status", "news"]].copy()
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
    print(table(pd.DataFrame(rows).sort_values(
        "pos", key=lambda s: s.map(POSITION_ORDER))))
