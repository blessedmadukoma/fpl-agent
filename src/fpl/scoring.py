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
# defensive contribution threshold per position
DEFCON_THRESHOLD = {"GKP": 10**9, "DEF": 10,
                    "MID": 12, "FWD": 12}  # GKP cannot earn it

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
    def from_game_config(cls, game_config: Mapping) -> Rules:
        return cls(coefficients=dict(game_config["scoring"]))

    def points(self, stat: str, position: str) -> int:
        """Points per unit of `stat` for `position` (some coefficients depend on position)"""
        value = self.coefficients[stat]
        return value[position] if isinstance(value, Mapping) else value


def score(stats: Mapping[str, float], position: str, rules: Rules) -> int:
    """Realised FPL points for one player in one fixture"""
    minutes = stats.get("minutes", 0)
    total = 0

    if minutes >= LONG_PLAY_MINUTES:
        total += rules.points("long_play", position)
    elif minutes > 0:
        total += rules.points("short_play", position)

    for stat in PER_UNIT_STATS:
        total += int(stats.get(stat, 0)) * rules.points(stat, position)

    conceded = int(stats.get("goals_conceded", 0))
    total += int(conceded // GOALS_CONCEDED_PER_POINT) * \
        rules.points("goals_conceded", position)

    saves = int(stats.get("saves", 0))
    total += (saves // SAVES_PER_POINT) * rules.points("saves", position)

    if stats.get("defensive_contribution", 0) >= DEFCON_THRESHOLD[position]:
        total += rules.points("defensive_contribution", position)

    return total
