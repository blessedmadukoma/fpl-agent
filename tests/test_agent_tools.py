"""Test the team tool with temporary frozen data and no network access."""

import json
import socket
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest
from pydantic import ValidationError

from fpl.agent import service
from fpl.agent.schemas import ChipValuesInput, RecommendationInput
from fpl.agent.service import load_file, run_tool, tool_definitions
from fpl.agent.tools import get_chip_values, get_my_team, get_recommendation
from fpl.config import Settings
from fpl.evals import snapshot
from fpl.evals.snapshot import create_snapshot, read_manifest, read_team_json
from fpl.storage import connect_path
from fpl.team_state import SquadPlayer, TeamState


@pytest.fixture
def frozen_team(tmp_path, monkeypatch):
    settings = Settings(entry_id=123, data_dir=tmp_path)
    elements = list(range(15, 0, -1))
    positions = ["GKP"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3
    team = TeamState(
        entry_id=123,
        team_name="Fixture FC",
        based_on_gw=5,
        squad=tuple(SquadPlayer(element, 50, 51) for element in elements),
        bank=10,
        free_transfers=2,
        chips_available=("wildcard (until GW19)",),
        chips_used=("freehit (GW3)",),
    )
    expected_players = [
        {
            "element_id": element,
            "player_name": f"Player {element}",
            "position": position,
            "club": "Fixture Club",
            "purchase_price": 50,
            "current_price": 52,
            "selling_price": 51,
            "price_change_since_purchase": 2,
            "status": "d" if element == 15 else "a",
            "news": "Fitness test" if element == 15 else None,
        }
        for element, position in zip(elements, positions)
    ]
    state_rows = [
        (
            "2026-27", 6, player["element_id"], player["player_name"],
            player["position"], 1, player["current_price"], player["status"],
            player["news"],
        )
        for player in expected_players
    ]
    with duckdb.connect(str(settings.db_path)) as con:
        con.execute(
            "create table events (season varchar, gw integer, deadline timestamptz)"
        )
        con.execute(
            "insert into events values ('2026-27', 6, '2026-10-10 10:00:00+00')"
        )
        for table in ("fixtures", "odds", "player_gw"):
            con.execute(f"create table {table} (season varchar, gw integer)")
        con.execute("create table rules (season varchar)")
        con.execute(
            "create table teams (season varchar, team_id integer, name varchar)"
        )
        con.execute(
            "insert into teams values ('2025-26', 1, 'Wrong Season Club'), "
            "('2026-27', 1, 'Fixture Club')"
        )
        con.execute(
            "create table state (season varchar, gw integer, element integer, "
            "web_name varchar, position varchar, team integer, now_cost integer, "
            "status varchar, news varchar)"
        )
        # Distracting rows catch queries that omit the season or GW filter.
        con.execute(
            "insert into state values "
            "('2025-26', 6, 15, 'Wrong Season Player', 'MID', 1, 99, 'a', ''), "
            "('2026-27', 5, 15, 'Wrong GW Player', 'MID', 1, 98, 'a', '')"
        )
        con.executemany(
            "insert into state values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            sorted(state_rows, key=lambda row: row[2]),
        )

        # Extend the fixture with data needed by the other tools and ep_next model.
        con.execute("alter table state add column ep_next double default 2.0")
        con.execute("update state set ep_next = 6 where element = 14")
        con.execute(
            "alter table events add column finished boolean default false")
        con.execute(
            "insert into events values ('2026-27', 5, '2026-10-01 10:00:00+00', true)"
        )
        for column, kind in (
            ("element", "integer"), ("position", "varchar"), ("team", "integer"),
            ("minutes", "double"), ("total_points", "double"),
            ("goals_scored", "double"), ("assists", "double"),
            ("clean_sheets", "double"),
        ):
            con.execute(f"alter table player_gw add column {column} {kind}")
        con.executemany(
            "insert into player_gw values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("2026-27", 5, p["element_id"], p["position"], 1, 90,
                 9 if p["element_id"] in {14, 15} else 3, 0, 0, 1)
                for p in expected_players
            ],
        )
        # A future row and another season must not enter historical answers.
        con.execute(
            "insert into player_gw values "
            "('2026-27', 6, 15, 'GKP', 1, 90, 100, 0, 0, 1), "
            "('2025-26', 5, 15, 'GKP', 1, 90, 999, 0, 0, 1)"
        )
        con.execute(
            "insert into teams values ('2026-27', 2, 'Club Two'), ('2026-27', 3, 'Club Three')")
        for column, kind in (
            ("fixture_id", "integer"), ("team_h", "integer"),
            ("team_a", "integer"), ("kickoff", "timestamptz"),
        ):
            con.execute(f"alter table fixtures add column {column} {kind}")
        con.executemany(
            "insert into fixtures values ('2026-27', ?, ?, ?, ?, ?)",
            [
                (5, 100, 1, 2, "2026-10-01T12:00:00+00:00"),
                (6, 101, 1, 2, "2026-10-10T12:00:00+00:00"),
                (7, 102, 1, 3, "2026-10-17T12:00:00+00:00"),
                (7, 103, 2, 1, "2026-10-18T12:00:00+00:00"),
                (8, 104, 2, 3, "2026-10-24T12:00:00+00:00"),
                (9, 105, 2, 1, "2026-10-31T12:00:00+00:00"),
            ],
        )
        for column, kind in (
            ("fixture_id", "integer"), ("team_h",
                                        "integer"), ("team_a", "integer"),
            ("lambda_h", "double"), ("lambda_a", "double"), ("source", "varchar"),
        ):
            con.execute(f"alter table odds add column {column} {kind}")
        con.execute(
            "insert into odds values "
            "('2026-27', 5, 100, 1, 2, 1.6, 0.8, 'result'), "
            "('2026-27', 6, 101, 1, 2, 1.8, 0.7, 'upcoming')"
        )

    monkeypatch.setattr(
        snapshot, "git_metadata", lambda: {
            "commit": "abc123def456", "dirty": False}
    )
    ctx = SimpleNamespace(
        season="2026-27",
        gw=6,
        deadline="2026-10-10T10:00:00+00:00",
        state=pd.DataFrame(state_rows, columns=[
            "season", "gw", "element", "web_name", "position", "team",
            "now_cost", "status", "news",
        ]),
    )
    result = create_snapshot(
        ctx, settings, "tool-test", team,
        update_summary={
            "season": "2026-27", "players": 15, "finished_gws": [1, 2, 3, 4, 5],
            "player_gw_rows": 0, "next_gw": 6, "next_deadline": ctx.deadline,
        },
    )
    directory = Path(result["final_path"])
    manifest = read_manifest(directory)
    payload, loaded_team = read_team_json(directory / "team.json")
    context = {
        "snapshot": result["validation_result"],
        "manifest": manifest,
        "payload": payload,
        "team": loaded_team,
    }

    def reject_network(*args, **kwargs):
        raise AssertionError("The team tool attempted network access")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket, "create_connection", reject_network)
    return SimpleNamespace(
        directory=directory,
        database_path=directory / "fpl.duckdb",
        context=context,
        expected_players=expected_players,
    )


def test_expected_team(frozen_team):
    result = load_file(frozen_team.directory)
    manifest = frozen_team.context["manifest"]

    assert result.snapshot_id == manifest["snapshot_id"]
    assert result.snapshot_created_at == datetime.fromisoformat(
        manifest["created_at"])
    assert result.season == "2026-27"
    assert result.target_gw == 6
    assert result.deadline == datetime(2026, 10, 10, 10, tzinfo=UTC)
    assert result.team_name == "Fixture FC"
    assert result.based_on_gw == 5
    assert result.bank_in_tenths == 10
    assert result.free_transfers == 2
    assert result.available_chips == ["wildcard (until GW19)"]
    assert result.used_chips == ["freehit (GW3)"]
    assert len({player.element_id for player in result.squad_players}) == 15
    assert [player.model_dump() for player in result.squad_players] == (
        frozen_team.expected_players
    )
    assert json.loads(result.model_dump_json())["squad_players"] == (
        frozen_team.expected_players
    )


def test_missing_player(frozen_team):
    with connect_path(frozen_team.database_path) as con:
        con.execute(
            "delete from state where season = '2026-27' and gw = 6 and element = 15")

    # Exercise the tool directly; the deliberate change invalidates snapshot hashes.
    with connect_path(frozen_team.database_path, read_only=True) as con:
        with pytest.raises(Exception, match="Player 15 not found in state table"):
            get_my_team(frozen_team.context, con)


def test_missing_club(frozen_team):
    with connect_path(frozen_team.database_path) as con:
        con.execute(
            "delete from teams where season = '2026-27' and team_id = 1")

    with connect_path(frozen_team.database_path, read_only=True) as con:
        with pytest.raises(Exception, match="Club with team ID 1 not found in teams table"):
            get_my_team(frozen_team.context, con)


def test_identical_json_response(frozen_team):
    first = load_file(frozen_team.directory).model_dump_json()
    second = load_file(frozen_team.directory).model_dump_json()

    assert first == second


def test_service_uses_read_only_database_and_closes_connection(frozen_team, monkeypatch):
    opened_connections = []

    def tracked_connect(path, read_only=False):
        assert path == frozen_team.database_path
        assert read_only is True
        con = connect_path(path, read_only=read_only)
        with pytest.raises(duckdb.InvalidInputException, match="read-only"):
            con.execute("create table forbidden_write (value integer)")
        opened_connections.append(con)
        return con

    monkeypatch.setattr(service, "connect_path", tracked_connect)
    load_file(frozen_team.directory)

    assert len(opened_connections) == 1
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        opened_connections[0].execute("select 1")


def test_invalid_snapshot_fails_before_tool_execution(frozen_team, monkeypatch):
    with (frozen_team.directory / "team.json").open("a", encoding="utf-8") as file:
        file.write(" ")

    def unexpected_tool_call(*args, **kwargs):
        raise AssertionError("Tool ran before snapshot validation succeeded")

    monkeypatch.setattr(service, "get_my_team", unexpected_tool_call)

    with pytest.raises(ValueError, match="file size"):
        load_file(frozen_team.directory)


def test_player_summary_uses_frozen_identity_and_excludes_future_results(frozen_team):
    result = run_tool(
        frozen_team.directory, "get_player_summary", {
            "element_id": 15, "model": "ep_next"}
    )

    assert result.player.player_name == "Player 15"
    assert result.player.club == "Fixture Club"
    assert result.projection.gw == 6
    assert result.projection.expected_points == 2.0
    assert [(row.gw, row.total_points) for row in result.history] == [(5, 9.0)]
    assert result.snapshot_id == frozen_team.context["manifest"]["snapshot_id"]
    assert result.as_of == datetime.fromisoformat(
        frozen_team.context["manifest"]["created_at"])
    assert json.loads(result.model_dump_json())[
        "projection"]["expected_points"] == 2


def test_comparison_preserves_requested_order_and_counts_double_and_blank_gws(frozen_team):
    result = run_tool(
        frozen_team.directory, "compare_players",
        {"element_ids": [15, 14], "horizon": 4, "model": "ep_next"},
    )

    assert result.gws == [6, 7, 8, 9]
    assert [player.player.element_id for player in result.players] == [15, 14]
    assert [gw.expected_points for gw in result.players[0].projections] == [
        2, 4, 0, 2]
    assert result.players[1].total_expected_points == 24
    assert [player.expected_points_behind_best for player in result.players] == [
        16, 0]
    assert result.best_element_ids == [14]


def test_fixture_outlook_distinguishes_odds_and_ratings(frozen_team):
    result = run_tool(
        frozen_team.directory, "get_fixture_outlook", {
            "team_id": 1, "horizon": 4}
    )

    assert result.club == "Fixture Club"
    assert [row.fixture_id for row in result.fixtures] == [101, 102, 103, 105]
    assert [row.gw for row in result.fixtures] == [6, 7, 7, 9]
    assert result.fixtures[0].opponent == "Club Two"
    assert result.fixtures[0].home is True
    assert result.fixtures[0].source == "odds"
    assert result.fixtures[0].expected_goals_for == 1.8
    assert result.fixtures[0].expected_goals_against == 0.7
    assert result.fixtures[0].clean_sheet_probability == pytest.approx(
        0.4965853)
    assert all(row.source == "ratings" for row in result.fixtures[1:])


def test_historical_leaders_filters_season_position_and_orders_ties(frozen_team):
    result = run_tool(
        frozen_team.directory, "get_historical_leaders",
        {"gw": 5, "statistic": "total_points", "position": "GKP", "limit": 2},
    )

    assert [(row.element_id, row.value)
            for row in result.leaders] == [(14, 9), (15, 9)]
    assert all(row.player_name !=
               "Wrong Season Player" for row in result.leaders)
    assert result.gw == 5
    assert result.target_gw == 6


@pytest.mark.parametrize("gw", [6, 7, 4])
def test_historical_leaders_rejects_unfinished_or_missing_gws(frozen_team, gw):
    with pytest.raises(ValueError, match="finished GW"):
        run_tool(frozen_team.directory, "get_historical_leaders", {"gw": gw})


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("get_player_summary", {"element_id": "15"}),
        ("compare_players", {"element_ids": [15, 15]}),
        ("compare_players", {"element_ids": [15]}),
        ("compare_players", {"element_ids": [15, 14], "horizon": 50}),
        ("get_fixture_outlook", {"team_id": 1, "horizon": 0}),
        ("get_historical_leaders", {
         "gw": 5, "statistic": "total_points; drop table state"}),
        ("get_historical_leaders", {"gw": 5, "limit": 100}),
        ("get_chip_values", {"horizon": 20}),
        ("get_my_team", {"snapshot_dir": "/arbitrary/path"}),
        ("get_recommendation", {"threshold": -1}),
        ("get_recommendation", {"threshold": float("inf")}),
        ("get_recommendation", {"max_hits": -1}),
    ],
)
def test_dispatch_rejects_invalid_arguments_before_loading(name, arguments, monkeypatch):
    def unexpected_load(*args, **kwargs):
        raise AssertionError("Snapshot loaded before validating arguments")

    monkeypatch.setattr(service, "open_snapshot", unexpected_load)
    with pytest.raises(ValidationError):
        run_tool(Path("unused"), name, arguments)


@pytest.mark.parametrize(
    ("name", "arguments", "message"),
    [
        ("get_player_summary", {"element_id": 999,
         "model": "ep_next"}, "Player 999"),
        ("compare_players", {"element_ids": [
         15, 999], "model": "ep_next"}, "Player 999"),
        ("get_fixture_outlook", {"team_id": 999}, "Club 999"),
    ],
)
def test_tools_reject_unknown_ids(frozen_team, name, arguments, message):
    with pytest.raises(LookupError, match=message):
        run_tool(frozen_team.directory, name, arguments)


def test_dispatch_includes_recommendation_and_rejects_unknown_tools():
    with pytest.raises(ValueError, match="Unknown or unimplemented tool"):
        run_tool(Path("unused"), "execute_sql")
    definitions = tool_definitions()
    assert len(definitions) == 7
    assert "get_recommendation" in {item["function"]["name"] for item in definitions}
    assert all(item["function"]["parameters"]
               ["additionalProperties"] is False for item in definitions)


def prepare_legal_squad(frozen_team):
    # Give owned players distinct clubs and add four equal-price stars from one club.
    with connect_path(frozen_team.database_path) as con:
        con.executemany(
            "insert into teams values ('2026-27', ?, ?)",
            [(club_id, f"Club {club_id}") for club_id in range(4, 16)]
            + [(99, "Star Club")],
        )
        con.execute(
            "update state set team = element, now_cost = 50, ep_next = 2 where season = '2026-27' and gw = 6")
        con.executemany(
            "insert into state values ('2026-27', 6, ?, ?, ?, 99, 50, 'a', null, 8)",
            [(16, "Star 16", "MID"), (17, "Star 17", "MID"),
             (18, "Star 18", "FWD"), (19, "Star 19", "DEF")],
        )
        con.execute("delete from fixtures")
        clubs = list(range(1, 16)) + [99]
        for index, (home, away) in enumerate(zip(clubs[::2], clubs[1::2]), start=1):
            con.execute(
                "insert into fixtures values ('2026-27', 6, ?, ?, ?, '2026-10-10T12:00:00+00')",
                [index, home, away],
            )
            con.execute(
                "insert into fixtures values ('2026-27', 7, ?, ?, ?, '2026-10-17T12:00:00+00')",
                [index + 8, away, home],
            )


def test_chip_values_reuses_real_optimizer_for_legal_squad(frozen_team):
    prepare_legal_squad(frozen_team)
    with connect_path(frozen_team.database_path, read_only=True) as con:
        result = get_chip_values(
            frozen_team.context, con, ChipValuesInput(
                horizon=1, model="ep_next")
        )

    assert result.values[0].gw == 6
    assert result.values[0].your_xi == 24
    assert result.values[0].triple_captain == 2
    assert result.values[0].bench_boost == 8
    assert result.values[0].free_hit == 24
    assert result.best_gws == {
        "triple_captain": 6, "bench_boost": 6, "free_hit": 6}
    assert result.available_chips == ["wildcard (until GW19)"]
    assert json.loads(result.model_dump_json())["values"][0]["free_hit"] == 24


@pytest.mark.parametrize(("threshold", "make_transfers"), [(2.5, True), (1000.0, False)])
def test_recommendation_selects_plan_using_threshold(frozen_team, threshold, make_transfers):
    prepare_legal_squad(frozen_team)
    with connect_path(frozen_team.database_path, read_only=True) as con:
        result = get_recommendation(
            frozen_team.context, con,
            RecommendationInput(model="ep_next", horizon=2, threshold=threshold),
        )

    assert result.actual_gws == [6, 7]
    assert result.threshold == threshold
    assert result.gain == pytest.approx(result.plan_objective - result.hold_objective)
    assert result.gain > 0
    assert result.make_transfers is make_transfers
    assert bool(result.selected_gw_plans[0].buys) is make_transfers
    assert result.allowed_hits == 0
    referenced_elements = set()
    for plan in result.selected_gw_plans:
        assert len(plan.team_xi) == 11
        assert len(plan.ordered_bench) == 4
        assert len(set(plan.team_xi + plan.ordered_bench)) == 15
        assert plan.captain in plan.team_xi
        assert plan.vice_captain in plan.team_xi
        assert plan.captain != plan.vice_captain
        assert plan.hits == 0
        referenced_elements.update(plan.buys + plan.sells + plan.team_xi + plan.ordered_bench)
    player_details = {player.element_id: player for player in result.players}
    assert len(player_details) == len(result.players)
    assert set(player_details) == referenced_elements
    assert player_details[15].player_name == "Player 15"
    assert player_details[15].club == "Club 15"
    transferred_stars = set(player_details) & {16, 17, 18, 19}
    assert transferred_stars
    for element in transferred_stars:
        assert player_details[element].player_name == f"Star {element}"
        assert player_details[element].club == "Star Club"
    payload = json.loads(result.model_dump_json())
    assert payload["make_transfers"] is make_transfers
    assert "ctx" not in payload


@pytest.mark.parametrize(("threshold", "captain_gain"), [(2.5, 8), (1000.0, 2)])
def test_chip_assessment_uses_the_threshold_selected_squad(frozen_team, threshold, captain_gain):
    prepare_legal_squad(frozen_team)
    frozen_team.context["team"] = replace(
        frozen_team.context["team"], chips_available=("3xc (until GW7)",),
    )
    with connect_path(frozen_team.database_path, read_only=True) as con:
        result = get_recommendation(
            frozen_team.context, con,
            RecommendationInput(model="ep_next", horizon=2, threshold=threshold),
        )
    decision = result.chip_decision
    assert decision.action == "use"
    assert decision.chip == "3xc"
    assert decision.evaluated_gws == [6, 7]
    option = next(option for option in decision.options if option.chip == "3xc")
    assert option.gain_now == captain_gain
    payload = json.loads(result.model_dump_json())
    assert payload["chip_decision"]["chip"] == "3xc"
