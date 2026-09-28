"""Multi-GW transfer optimiser: a mixed-integer linear program (MILP)

Decision per player p and GW g: in the squad (x), in the XI (y), captain (c), bought, sold.
Constraints: squad rules, club limit, budget with selling prices, free-transfer rollover.
Objective: discounted expected points of XI + captain, a little for the bench, minus hits.
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
    # makes the reported free-transfer count exact (H.9)
    free_transfer_bonus: float = 0.01
    allow_transfers: bool = True
    # no transfers in the first GW, later ones allowed ("roll")
    hold_first_gw: bool = False
    # plus your own players; keeps the problem small
    candidates_per_position: int = 50
    time_limit_s: int = 60


@dataclass
class GwPlan:
    gw: int
    buy: list[int]
    sell: list[int]
    xi: list[int]
    # in autosub order; the reserve goalkeeper is always first
    bench: list[int]
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
    sell_value = {p: team.selling_prices().get(
        p, int(info.at[p, "now_cost"])) for p in pool}

    model = pulp.LpProblem("fpl", pulp.LpMaximize)

    def per_player(name): return model.add_variable_dicts(
        name, (pool, gws), lowBound=0, upBound=1, cat="Binary")
    per_gw = lambda name, **kwargs: model.add_variable_dicts(
        name, gws, **kwargs)
    x, y, c, buy, sell = (per_player(n)
                          for n in ("squad", "xi", "captain", "buy", "sell"))
    free = per_gw("free", lowBound=0,
                  upBound=settings.max_free_transfers, cat="Integer")
    carry = per_gw("carry", lowBound=0,
                   upBound=settings.max_free_transfers, cat="Integer")
    has_carry = per_gw("has_carry", cat="Binary")
    hits = per_gw("hits", lowBound=0, cat="Integer")
    bank = per_gw("bank", lowBound=0)
    big_m = 20

    for i, g in enumerate(gws):
        previous = (lambda p: 1 if p in owned else 0) if i == 0 else (
            lambda p, g0=gws[i - 1]: x[p][g0])
        previous_bank = team.bank if i == 0 else bank[gws[i - 1]]
        used = pulp.lpSum(buy[p][g] for p in pool)

        # Squad and XI rules
        model += pulp.lpSum(x[p][g] for p in pool) == 15
        model += pulp.lpSum(y[p][g] for p in pool) == 11
        model += pulp.lpSum(c[p][g] for p in pool) == 1
        for position, quota in SQUAD_QUOTA.items():
            members = [
                p for p in pool if info.at[p, "position"] == position]
            low, high = XI_RANGE[position]
            model += pulp.lpSum(x[p][g] for p in members) == quota
            model += pulp.lpSum(y[p][g] for p in members) >= low
            model += pulp.lpSum(y[p][g] for p in members) <= high
        for club in info.team.unique():
            model += pulp.lpSum(x[p][g]
                                for p in pool if info.at[p, "team"] == club) <= CLUB_LIMIT
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
        weight[g] * float(ep.at[p, g]) * (y[p][g] + c[p][g] +
                                          settings.bench_weight * (x[p][g] - y[p][g]))
        for p in pool for g in gws
    )
    penalties = pulp.lpSum(
        weight[g] * settings.hit_cost * hits[g] for g in gws)
    model += points - penalties + settings.free_transfer_bonus * \
        pulp.lpSum(free[g] for g in gws)

    solve_stats = model.solve(_solver(settings))
    if solve_stats.status != pulp.LpSolveStatus.Optimal:
        raise RuntimeError(
            f"Solver finished with status {solve_stats.status_str}")

    plan = Plan(objective=float(pulp.value(points - penalties)))
    for g in gws:
        def chosen(var): return [p for p in pool if var[p][g].value() > 0.5]
        xi = chosen(y)
        captain = chosen(c)[0]
        bench = [p for p in chosen(x) if p not in xi]
        plan.gws.append(
            GwPlan(
                gw=g,
                buy=chosen(buy),
                sell=chosen(sell),
                xi=sorted(xi, key=lambda p: (list(SQUAD_QUOTA).index(
                    info.at[p, "position"]), -ep.at[p, g])),
                bench=_bench_order(bench, ep[g], info),
                captain=captain,
                vice=max((p for p in xi if p != captain),
                         key=lambda p: ep.at[p, g]),
                free_transfers=round(free[g].value()),
                hits=round(hits[g].value()),
                expected_points=float(
                    sum(ep.at[p, g] for p in xi) + ep.at[captain, g]),
            )
        )
    return plan


def _candidate_pool(ep: pd.DataFrame, info: pd.DataFrame, team: TeamState, settings: SolverSettings) -> list[int]:
    """Your players plus the best N per position by total expected points."""
    total = ep.sum(axis=1).rename("total").to_frame().join(info.position)
    best = total.sort_values("total", ascending=False).groupby(
        "position").head(settings.candidates_per_position)
    return sorted(set(best.index) | set(team.elements))


def _bench_order(bench: list[int], ep: pd.Series, info: pd.DataFrame) -> list[int]:
    goalkeeper = [p for p in bench if info.at[p, "position"] == "GKP"]
    outfield = sorted(
        (p for p in bench if p not in goalkeeper), key=lambda p: -ep[p])
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
