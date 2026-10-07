from contextlib import contextmanager
from pathlib import Path

from fpl.agent.schemas import (
    ChipValuesInput,
    ComparePlayersInput,
    FixtureOutlookInput,
    HistoricalLeadersInput,
    MyTeamInput,
    PlayerSummaryInput,
    RecommendationInput,
)
from fpl.agent.tools import (
    compare_players,
    get_chip_values,
    get_fixture_outlook,
    get_historical_leaders,
    get_my_team,
    get_player_summary,
    get_recommendation,
)
from fpl.evals.snapshot import read_manifest, read_team_json, validate_snapshot
from fpl.storage import connect_path

TOOL_REGISTRY = {
    "get_my_team": (MyTeamInput, get_my_team),
    "get_player_summary": (PlayerSummaryInput, get_player_summary),
    "compare_players": (ComparePlayersInput, compare_players),
    "get_fixture_outlook": (FixtureOutlookInput, get_fixture_outlook),
    "get_chip_values": (ChipValuesInput, get_chip_values),
    "get_historical_leaders": (HistoricalLeadersInput, get_historical_leaders),
    "get_recommendation": (RecommendationInput, get_recommendation)
}


@contextmanager
def open_snapshot(snapshot_dir: Path):
    """Yield loaded frozen resources and close the read-only connection on exit."""
    snapshot_dir = Path(snapshot_dir)
    snapshot_data = validate_snapshot(snapshot_dir)

    manifest = read_manifest(snapshot_dir)

    database_path = snapshot_dir / "fpl.duckdb"
    team_path = snapshot_dir / "team.json"

    payload, team = read_team_json(team_path)

    snapshot_context = {
        "snapshot": snapshot_data,
        "manifest": manifest,
        "payload": payload,
        "team": team,
    }

    with connect_path(database_path, read_only=True) as con:
        yield snapshot_context, con


def load_file(snapshot_dir: Path):
    """Retain the original entry point for the user's get_my_team implementation."""
    with open_snapshot(snapshot_dir) as (snapshot_context, con):
        return get_my_team(snapshot_context, con)


def run_tool(snapshot_dir: Path, tool_name: str, arguments: dict | None = None):
    """Validate arguments and invoke only a registered tool on the chosen snapshot."""
    if tool_name not in TOOL_REGISTRY:
        raise ValueError(f"Unknown or unimplemented tool: {tool_name}")
    schema, function = TOOL_REGISTRY[tool_name]
    request = schema.model_validate(arguments if arguments is not None else {})
    with open_snapshot(snapshot_dir) as (snapshot_context, con):
        if tool_name == "get_my_team":
            return function(snapshot_context, con)
        return function(snapshot_context, con, request)


def tool_definitions() -> list[dict]:
    """Expose the names, descriptions and argument schemas for future tool calling."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": function.__doc__.strip().split("\n\n", 1)[0],
                "parameters": schema.model_json_schema(),
            },
        }
        for name, (schema, function) in TOOL_REGISTRY.items()
    ]
