from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SquadPlayerSchema(BaseModel):
    element_id: int
    player_name: str
    position: str
    club: str
    purchase_price: int
    current_price: int
    selling_price: int
    status: str
    news: str | None = None


class MyTeamSchema(BaseModel):
    snapshot_id: str
    snapshot_created_at: datetime
    season: str
    target_gw: int
    deadline: datetime
    team_name: str
    based_on_gw: int
    bank_in_tenths: int
    free_transfers: int
    available_chips: list[str]
    used_chips: list[str]
    squad_players: list[SquadPlayerSchema]


Position = Literal["GKP", "DEF", "MID", "FWD"]
ProjectionModel = Literal["full", "shrunk_blend",
                          "blend", "ep_next", "ppg", "form", "zero"]
ElementId = Annotated[int, Field(strict=True, gt=0)]
Gameweek = Annotated[int, Field(strict=True, ge=1, le=38)]
Horizon = Annotated[int, Field(strict=True, ge=1, le=6)]


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MyTeamInput(ToolInput):
    """No model-supplied arguments: the application selects the snapshot."""


class PlayerSummaryInput(ToolInput):
    element_id: ElementId
    model: ProjectionModel = "full"
    history_gws: Annotated[int, Field(strict=True, ge=1, le=38)] = 5


class ComparePlayersInput(ToolInput):
    element_ids: Annotated[list[ElementId], Field(min_length=2, max_length=5)]
    horizon: Horizon = 4
    model: ProjectionModel = "full"

    @field_validator("element_ids")
    @classmethod
    def unique_elements(cls, values: list[int]) -> list[int]:
        if len(set(values)) != len(values):
            raise ValueError("Choose distinct player IDs")
        return values


class FixtureOutlookInput(ToolInput):
    team_id: ElementId
    horizon: Horizon = 4


class ChipValuesInput(ToolInput):
    horizon: Annotated[int, Field(strict=True, ge=1, le=14)] = 4
    model: ProjectionModel = "full"


class HistoricalLeadersInput(ToolInput):
    gw: Gameweek
    statistic: Literal["total_points", "minutes",
                       "goals_scored", "assists", "clean_sheets"] = "total_points"
    position: Position | None = None
    limit: Annotated[int, Field(strict=True, ge=1, le=20)] = 5


class RecommendationInput(ToolInput):
    horizon: Annotated[int, Field(strict=True, ge=1, le=6)] = 4
    model: ProjectionModel = "full"
    threshold: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 2.0
    max_hits: Annotated[int, Field(strict=True, ge=0)] = 0


class SnapshotMetadata(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    snapshot_id: str
    as_of: datetime
    season: str
    target_gw: int


class PlayerDetails(BaseModel):
    element_id: int
    player_name: str
    position: Position
    club: str
    current_price: int
    status: str
    news: str | None = None


class PlayerGwResult(BaseModel):
    gw: int
    minutes: float
    total_points: float
    goals_scored: float
    assists: float
    clean_sheets: float


class PlayerProjection(BaseModel):
    gw: int
    expected_points: float


class PlayerSummaryResult(SnapshotMetadata):
    player: PlayerDetails
    history: list[PlayerGwResult]
    projection: PlayerProjection
    model: ProjectionModel


class ComparedPlayer(BaseModel):
    player: PlayerDetails
    projections: list[PlayerProjection]
    total_expected_points: float


class ComparePlayersResult(SnapshotMetadata):
    gws: list[int]
    model: ProjectionModel
    players: list[ComparedPlayer]
    best_element_ids: list[int]


class FixtureProjection(BaseModel):
    fixture_id: int
    gw: int
    opponent_id: int
    opponent: str
    home: bool
    expected_goals_for: float
    expected_goals_against: float
    clean_sheet_probability: float
    source: Literal["odds", "ratings"]


class FixtureOutlookResult(SnapshotMetadata):
    team_id: int
    club: str
    gws: list[int]
    fixtures: list[FixtureProjection]


class ChipGwValues(BaseModel):
    gw: int
    your_xi: float
    triple_captain: float
    bench_boost: float
    free_hit: float


class ChipValuesResult(SnapshotMetadata):
    model: ProjectionModel
    values: list[ChipGwValues]
    best_gws: dict[str, int]
    available_chips: list[str]
    assumptions: list[str]


class HistoricalLeader(BaseModel):
    rank: int
    element_id: int
    player_name: str
    position: Position
    club: str
    value: float


class HistoricalLeadersResult(SnapshotMetadata):
    gw: int
    statistic: str
    position: Position | None
    leaders: list[HistoricalLeader]


class SelectedGwPlan(BaseModel):
    gw: int
    buys: list[int]
    sells: list[int]
    team_xi: list[int]
    ordered_bench: list[int]
    captain: int
    vice_captain: int
    hits: int
    expected_points: float


class RecommendationResult(SnapshotMetadata):
    model: ProjectionModel
    actual_gws: list[int]
    threshold: float
    allowed_hits: int
    plan_objective: float          # transfers allowed in every GW
    # no transfer this GW (roll it), transfers allowed later
    hold_objective: float
    gain: float
    make_transfers: bool
    selected_gw_plans: list[SelectedGwPlan]
    assumptions: list[str]
