"""Plan available chips within their current windows using fixed-squad EP."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from itertools import product
from typing import Literal

import pandas as pd

from fpl.optimise.chips import chip_values
from fpl.team_state import TeamState

CHIPS = {
    "3xc": ("Triple Captain", "triple_captain"),
    "bboost": ("Bench Boost", "bench_boost"),
    "freehit": ("Free Hit", "free_hit"),
    "wildcard": ("Wildcard", None),
}


@dataclass(frozen=True)
class ChipOption:
    chip: str
    name: str
    available: bool
    expires_gw: int | None = None
    gain_now: float | None = None
    best_gw: int | None = None
    best_gain: float | None = None
    planned_gw: int | None = None
    planned_gain: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class ChipDecision:
    action: Literal["use", "save", "review_required", "none_available"]
    chip: str | None
    reason: str
    evaluated_gws: list[int]
    options: list[ChipOption]
    assumptions: list[str]


def _windows(team: TeamState) -> dict[str, int]:
    windows = {}
    for description in team.chips_available:
        match = re.fullmatch(r"(\w+) \(until GW(\d+)\)", description)
        if match is None or match[1] not in CHIPS:
            raise ValueError(f"Unrecognised chip availability: {description}")
        expiry = int(match[2])
        if not 1 <= expiry <= 38:
            raise ValueError("Chip expiry must be a valid gameweek")
        windows[match[1]] = expiry
    return windows


def chip_projection_gws(team: TeamState, first_gw: int) -> list[int]:
    """Look through chip expiry, independently of the transfer horizon."""
    ends = [end for chip, end in _windows(team).items()
            if CHIPS[chip][1] is not None and end >= first_gw]
    return list(range(first_gw, min(max(ends), 38) + 1)) if ends else []


def assess_chips(
    ep: pd.DataFrame, players: pd.DataFrame, team: TeamState,
) -> ChipDecision:
    """Value the supplied squad; transfer chips need additional plan review."""
    first_gw = int(ep.columns[0])
    required = chip_projection_gws(team, first_gw)
    if not set(required) <= set(ep.columns):
        windows = _windows(team)
        return ChipDecision(
            "review_required", None,
            "Chip timing needs projections through expiry; the ordinary transfer plan is unchanged.",
            [int(gw) for gw in ep.columns],
            [ChipOption(chip, name, chip in windows, windows.get(chip),
                        reason="Full-window projections are missing." if chip in windows else "Not available.")
             for chip, (name, _) in CHIPS.items()],
            ["No chip timing decision was made from the incomplete projection window."],
        )
    valued = any(CHIPS[chip][1] is not None for chip in _windows(team))
    values = chip_values(ep, players, team) if valued else pd.DataFrame()
    return decide_chips(values, team, first_gw)


def decide_chips(values: pd.DataFrame, team: TeamState, first_gw: int) -> ChipDecision:
    """Maximise incremental EP with one chip per GW and one use per chip.

    This schedules a fixed squad. It does not jointly optimise permanent
    transfers, Wildcards, or the future consequences of a Free Hit.
    """
    windows = {chip: end for chip, end in _windows(team).items() if end >= first_gw}
    gws = sorted(int(gw) for gw in values.get("gw", []))
    assumptions = [
        "Uses the selected first-GW squad unchanged in future GWs; rerun after transfers or team news.",
        "Uses current availability and minutes estimates; future injury recovery is not forecast.",
        "Schedules at most one valued chip per GW within its availability window.",
        "Wildcard is not valued. Free Hit requires review because it changes and then restores the squad.",
        "Starting-XI EP and the transfer objective exclude chip effects; gains are reported separately.",
    ]
    if not windows:
        return ChipDecision("none_available", None, "No chips are available.", gws, [], assumptions)

    frame = values.set_index("gw") if not values.empty else pd.DataFrame()
    gains = {}
    choices = {}
    for chip, expiry in windows.items():
        column = CHIPS[chip][1]
        if column is None:
            continue
        if first_gw not in frame.index or expiry not in frame.index:
            raise ValueError("Chip projections must cover the current GW through expiry")
        eligible = list(range(first_gw, expiry + 1))
        if any(gw not in frame.index for gw in eligible):
            raise ValueError("Chip projections contain a gap before expiry")
        if chip == "freehit" and f"freehit (GW{first_gw - 1})" in team.chips_used:
            eligible.remove(first_gw)
        gains[chip] = {}
        for gw in eligible:
            gain = float(frame.at[gw, column])
            if not math.isfinite(gain):
                raise ValueError("Chip values must be finite")
            gains[chip][gw] = max(0.0, gain)
        choices[chip] = [None, *(gw for gw in eligible if gains[chip][gw] > 0)]

    chips = list(choices)
    schedules = product(*(choices[chip] for chip in chips))

    def score(schedule):
        total = sum(gains[chip][gw] for chip, gw in zip(chips, schedule) if gw is not None)
        return round(total, 12), tuple(-gw if gw is not None else -39 for gw in schedule)

    legal = (schedule for schedule in schedules
             if len([gw for gw in schedule if gw is not None])
             == len({gw for gw in schedule if gw is not None}))
    selected = dict(zip(chips, max(legal, key=score)))
    options = []
    for chip, (name, column) in CHIPS.items():
        if chip not in windows:
            options.append(ChipOption(chip, name, False, reason="Not available."))
            continue
        if column is None:
            options.append(ChipOption(chip, name, True, windows[chip],
                                      reason="Manual review: Wildcard is not valued."))
            continue
        best = max(gains[chip], key=lambda gw: (gains[chip][gw], -gw), default=None)
        planned = selected[chip]
        options.append(ChipOption(
            chip, name, True, windows[chip], gains[chip].get(first_gw),
            best, gains[chip].get(best), planned, gains[chip].get(planned),
            "Unavailable this GW after last GW's Free Hit." if chip == "freehit" and first_gw not in gains[chip]
            else "Free Hit needs transfer-plan review." if chip == "freehit"
            else "Timing uses fixed-squad projected gains.",
        ))

    now = next((chip for chip, gw in selected.items() if gw == first_gw), None)
    if now == "freehit":
        action, reason = "review_required", "Free Hit has a projected opportunity now; review the full transfer and reversion plan before using it."
    elif now is not None:
        action, reason = "use", f"{CHIPS[now][0]} is allocated to GW{first_gw} in the projected chip schedule."
    elif chips:
        action = "save"
        reason = ("Save the valued chips this GW; the projected schedule favours later opportunities."
                  if any(gw is not None for gw in selected.values())
                  else "No positive gain is projected for the valued chips.")
        if "wildcard" in windows:
            reason += " Wildcard remains unassessed."
    else:
        action, reason = "review_required", "Only unvalued chips are available; a manual Wildcard review is required."
    return ChipDecision(action, now, reason, gws, options, assumptions)
