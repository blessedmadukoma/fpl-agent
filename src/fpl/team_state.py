"""Rebuild my current squad, bank, free transfers and chips from public endpoints.

No login is needed. The picks for a GW become public once its deadline has passed.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from fpl.config import Settings
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
    """The context for the next GW and the squad I carry into it."""
    ctx = load_context(con, Settings.current_season, next_gw(con))
    return ctx, reconstruct(client, entry_id, ctx.state, ctx.gw, client.bootstrap())


def reconstruct(client: FplClient, entry_id: int, players: pd.DataFrame, next_gw: int, boot: dict) -> TeamState:
    """Return the squad I will carry into `next_gw`.

    `players` must have element, now_cost and cost_change_start (the current snapshot).
    """
    entry = client.entry(entry_id)
    history = client.entry_history(entry_id)
    transfers = client.entry_transfers(entry_id)
    chips_by_gw = {c["event"]: c["name"] for c in history["chips"]}
    last_gw = max(row["event"] for row in history["current"])

    # After a Free Hit, the picks for that GW are the Free Hit squad; the real squad reverted.
    base_gw = last_gw - 1 if chips_by_gw.get(last_gw) == "freehit" else last_gw
    squad = [pick["element"]
             for pick in client.entry_picks(entry_id, base_gw)["picks"]]

    applied = [
        t for t in sorted(transfers, key=lambda t: t["time"])
        if t["event"] > base_gw and chips_by_gw.get(t["event"]) != "freehit"
    ]
    for t in applied:
        squad[squad.index(t["element_out"])] = t["element_in"]

    bank_row = next(
        row for row in history["current"] if row["event"] == base_gw)
    bank = bank_row["bank"] + \
        sum(t["element_out_cost"] - t["element_in_cost"] for t in applied)

    prices = players.set_index("element")
    purchase = _purchase_prices(
        client, squad, transfers, chips_by_gw, prices, entry["started_event"])
    members = tuple(
        SquadPlayer(e, purchase[e], selling_price(purchase[e], int(prices.at[e, "now_cost"]))) for e in squad
    )

    max_free = 1 + boot["game_config"]["rules"]["max_extra_free_transfers"]
    free = free_transfers(
        history["current"], chips_by_gw, entry["started_event"], max_free) - len(applied)

    return TeamState(
        entry_id=entry_id,
        team_name=entry["name"],
        based_on_gw=base_gw,
        squad=members,
        bank=bank,
        free_transfers=max(free, 0),
        chips_available=chips_available(boot["chips"], chips_by_gw, next_gw),
        chips_used=tuple(f"{name} (GW{gw})" for gw,
                         name in sorted(chips_by_gw.items())),
    )


def free_transfers(current: list[dict], chips_by_gw: dict[int, str], started_event: int, max_free: int) -> int:
    """Free transfers available for the GW after the last finished one.

    Normal week: unused transfers roll over (+1 a week, capped). A hit leaves me with 1.
    Wildcard or Free Hit week: saved transfers are kept, with no +1 (FPL rules text).
    """
    free = 1  # the first GW after I join
    for row in sorted(current, key=lambda r: r["event"]):
        if row["event"] <= started_event:
            continue
        if chips_by_gw.get(row["event"]) in TRANSFER_CHIPS:
            continue
        free = min(max_free, max(free - row["event_transfers"], 0) + 1)
    return free


def chips_available(chip_windows: list[dict], chips_by_gw: dict[int, str], next_gw: int) -> tuple[str, ...]:
    """Chips I can play in `next_gw`, with the GW they expire."""
    available = []
    for chip in chip_windows:
        window = range(chip["start_event"], chip["stop_event"] + 1)
        used = any(
            name == chip["name"] and gw in window for gw, name in chips_by_gw.items())
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
            result[element] = int(
                prices.at[element, "now_cost"] - prices.at[element, "cost_change_start"])
        else:  # joined later: the price in the round you joined
            rounds = client.element_summary(element)["history"]
            result[element] = next(r["value"]
                                   for r in rounds if r["round"] >= started_event)
    return result
