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


def print_recommendation(result) -> None:
    who = names(result.ctx)
    def label(p): return f"{who.at[p, 'web_name']} ({who.at[p, 'club']})"
    first = result.plan.gws[0]
    horizon = f"GW{result.plan.gws[0].gw}-{result.plan.gws[-1].gw}"
    print(f"{result.team.team_name}: GW{result.ctx.gw} recommendation, horizon {horizon}")
    print(
        f"Bank {money(result.team.bank)} | Free transfers {result.team.free_transfers}")
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
    print(
        f"Starting XI for GW{chosen.gw} (expected points incl. captain: {chosen.expected_points:.1f})")
    for p in chosen.xi:
        tag = " (C)" if p == chosen.captain else " (V)" if p == chosen.vice else ""
        print(f"  {who.at[p, 'position']}  {label(p):<28} {ep[p]:5.2f}{tag}")
    print("Bench, in order: " +
          ", ".join(f"{label(p)} {ep[p]:.2f}" for p in chosen.bench))
    later = [g for g in result.plan.gws[1:] if g.buy]
    if later:
        print()
        print("Planned later (not an action now): " + "; ".join(
            f"GW{g.gw}: " + ", ".join(f"{who.at[o, 'web_name']} -> {who.at[i, 'web_name']}"
                                      for o, i in zip(g.sell, g.buy)) for g in later))


def print_runs(settled: int, history: pd.DataFrame) -> None:
    print(f"Settled {settled} run(s).")
    if history.empty:
        print("No saved runs yet. Save one with: fpl recommend --save")
    else:
        print(table(history))


def print_odds_load(summary: dict) -> None:
    print(
        f"{summary['season']}: odds for {summary['fixtures']} fixtures ({summary['upcoming']} upcoming)")


def print_fixture_ticker(view: pd.DataFrame, ctx) -> None:
    """Clean-sheet % per team per GW; '*' marks bookmaker odds, no mark means team ratings."""
    short = ctx.teams.set_index("team_id").short_name
    view = view.assign(club=view.team.map(short), opp=view.opponent.map(short))

    def cell(
        r): return f"{r.opp}({'H' if r.home else 'A'}) {100 * r.p_clean_sheet:3.0f}%{'*' if r.source == 'odds' else ' '}"
    grid = view.assign(cell=view.apply(cell, axis=1)).pivot_table(
        index="club", columns="gw", values="cell", aggfunc=" / ".join)
    grid["avg"] = view.groupby("club").p_clean_sheet.mean()
    grid = grid.sort_values("avg", ascending=False)
    grid["avg"] = (100 * grid["avg"]).map("{:.0f}%".format)
    print(
        f"Clean-sheet chance by GW from GW{ctx.gw} (* = bookmaker odds, otherwise team ratings)")
    print(grid.to_string())


def print_projections(rows: pd.DataFrame, ctx, top: int, position: str | None) -> None:
    short = ctx.teams.set_index("team_id").short_name
    rows = rows.assign(player=rows.element.map(
        names(ctx).web_name), club=rows.team.map(short))
    if position:
        rows = rows[rows.position == position.upper()]
    columns = ["player", "club", "position", "p_start", "p_60", "pts_appearance", "pts_goals", "pts_assists",
               "pts_clean_sheet", "pts_defcon", "pts_bonus", "ep"]
    print(f"GW{ctx.gw} expected points, top {top}" +
          (f" {position.upper()}" if position else ""))
    print(table(rows.sort_values("ep", ascending=False)[columns].head(top)))


def print_chips(values: pd.DataFrame, team) -> None:
    print(
        f"Chip values for {team.team_name}'s current squad (expected points the chip adds)")
    print(table(values, "{:.1f}"))
    print()
    for chip in ("triple_captain", "bench_boost", "free_hit"):
        best = values.loc[values[chip].idxmax()]
        print(
            f"Best GW for {chip.replace('_', ' ')}: GW{int(best.gw)} (+{best[chip]:.1f})")
    print(
        f"Chips still available: {', '.join(team.chips_available) or 'none'}")
