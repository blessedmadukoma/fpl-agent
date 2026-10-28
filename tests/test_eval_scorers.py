"""Offline checks for tool selection and argument scoring."""

import json
import socket
from copy import deepcopy

import pytest

from fpl.evals import scorers


@pytest.fixture(autouse=True)
def no_external_execution(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Scorers must not use tools or the network")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)
    for name, (schema, _) in list(scorers.TOOL_REGISTRY.items()):
        monkeypatch.setitem(
            scorers.TOOL_REGISTRY, name, (schema, reject),
        )


def make_case(name, expected_arguments):
    return {
        "id": "test-case",
        "expected_tools": [name],
        "expected_arguments": {name: expected_arguments},
    }


def make_call(name, arguments, status="completed"):
    return {
        "tool_call_id": "test-call",
        "name": name,
        "raw_arguments": json.dumps(arguments),
        "arguments": arguments,
        "status": status,
    }


def chip_case():
    return make_case(
        "get_chip_values", {"horizon": 1, "model": "full"},
    )


def test_tool_selection_accepts_helper_and_duplicate_calls():
    case = {
        "expected_tools": ["get_my_team", "get_player_summary"],
    }
    saved_result = {"tool_calls": [
        make_call("get_fixture_outlook", {"team_id": 1}),
        make_call("get_player_summary", {"element_id": 411}),
        make_call("get_my_team", {}),
        make_call("get_my_team", {}),
    ]}

    assert scorers.score_tool_selection(case, saved_result) == {
        "score": 1, "missing_tools": [],
    }


def test_tool_selection_reports_sorted_missing_tools():
    case = {
        "expected_tools": [
            "get_player_summary", "get_fixture_outlook", "get_my_team",
        ],
    }
    saved_result = {"tool_calls": [make_call("get_my_team", {})]}

    assert scorers.score_tool_selection(case, saved_result) == {
        "score": 0,
        "missing_tools": ["get_fixture_outlook", "get_player_summary"],
    }


def test_tool_selection_distinguishes_request_from_execution():
    case = make_case("get_my_team", {})
    saved_result = {"tool_calls": [
        make_call("get_my_team", None, status="error"),
    ]}

    assert scorers.score_tool_selection(case, saved_result) == {
        "score": 1, "missing_tools": [],
    }
    assert scorers.score_arguments(case, saved_result)["score"] == 0


def test_tool_selection_fails_for_recorded_empty_calls():
    case = make_case("get_my_team", {})

    assert scorers.score_tool_selection(case, {"tool_calls": []}) == {
        "score": 0, "missing_tools": ["get_my_team"],
    }


def test_tool_selection_allows_no_required_tools():
    assert scorers.score_tool_selection(
        {"expected_tools": []}, {"tool_calls": []},
    ) == {"score": 1, "missing_tools": []}


@pytest.mark.parametrize("scorer", [
    scorers.score_tool_selection,
    scorers.score_arguments,
])
def test_missing_recording_is_not_scored_as_no_calls(scorer):
    with pytest.raises(ValueError, match="Tool calls were not recorded"):
        scorer(make_case("get_my_team", {}), {})


def test_empty_bank_arguments_pass():
    case = make_case("get_my_team", {})
    saved_result = {"tool_calls": [make_call("get_my_team", {})]}

    assert scorers.score_arguments(case, saved_result) == {
        "score": 1, "issues": [],
    }


def test_arguments_report_missing_required_call():
    saved_result = {"tool_calls": [make_call("get_my_team", {})]}

    assert scorers.score_arguments(chip_case(), saved_result) == {
        "score": 0,
        "issues": ["Missing tool call: get_chip_values"],
    }


def test_correct_chip_arguments_pass():
    saved_result = {"tool_calls": [make_call(
        "get_chip_values", {"horizon": 1, "model": "full"},
    )]}

    assert scorers.score_arguments(chip_case(), saved_result) == {
        "score": 1, "issues": [],
    }


@pytest.mark.parametrize("arguments,field", [
    ({"horizon": 6, "model": "full"}, "horizon"),
    ({"horizon": 1, "model": "form"}, "model"),
])
def test_schema_valid_but_wrong_values_fail(arguments, field):
    saved_result = {"tool_calls": [
        make_call("get_chip_values", arguments),
    ]}

    scored = scorers.score_arguments(chip_case(), saved_result)

    assert scored["score"] == 0
    assert len(scored["issues"]) == 1
    assert f"Mismatch for field '{field}'" in scored["issues"][0]


@pytest.mark.parametrize("arguments", [
    {"horizon": "1"},
    {"horizon": True},
    {"horizon": 1.5},
    {"horizon": 0},
    {"horizon": 15},
    {"horizon": 1, "model": "unknown-model"},
    {"horizon": 1, "unexpected": True},
    None,
    [],
    "{}",
])
def test_schema_invalid_arguments_fail(arguments):
    saved_result = {"tool_calls": [
        make_call("get_chip_values", arguments),
    ]}

    assert scorers.score_arguments(chip_case(), saved_result) == {
        "score": 0,
        "issues": ["Validation error in get_chip_values (call 0)"],
    }


@pytest.mark.parametrize("case,name,arguments", [
    (chip_case(), "get_chip_values", {"horizon": 1}),
    (
        make_case("get_player_summary", {
            "element_id": 411, "history_gws": 5,
        }),
        "get_player_summary",
        {"element_id": 411},
    ),
])
def test_schema_defaults_are_used_before_comparison(
    case, name, arguments,
):
    saved_result = {"tool_calls": [make_call(name, arguments)]}

    assert scorers.score_arguments(case, saved_result) == {
        "score": 1, "issues": [],
    }


@pytest.mark.parametrize("element_ids,expected_score", [
    ([411, 379], 1),
    ([379, 411], 1),
    ([411, 999], 0),
    ([411, 411], 0),
    ([411, -1], 0),
    (["411", 379], 0),
    ([True, 379], 0),
])
def test_player_ids_are_unordered_but_still_validated(
    element_ids, expected_score,
):
    case = make_case("compare_players", {
        "element_ids": [411, 379], "horizon": 4, "model": "full",
    })
    saved_result = {"tool_calls": [make_call(
        "compare_players", {"element_ids": element_ids},
    )]}

    scored = scorers.score_arguments(case, saved_result)

    assert scored["score"] == expected_score
    assert bool(scored["issues"]) == (expected_score == 0)


def test_helper_calls_do_not_need_expected_arguments():
    saved_result = {"tool_calls": [
        make_call("get_my_team", {}),
        make_call("get_chip_values", {"horizon": 1}),
    ]}

    assert scorers.score_arguments(chip_case(), saved_result) == {
        "score": 1, "issues": [],
    }


def test_every_repeated_required_call_is_checked():
    saved_result = {"tool_calls": [
        make_call("get_chip_values", {"horizon": 1}),
        make_call("get_chip_values", {"horizon": 6}),
    ]}

    scored = scorers.score_arguments(chip_case(), saved_result)

    assert scored["score"] == 0
    assert len(scored["issues"]) == 1
    assert "(call 1)" in scored["issues"][0]
    assert "expected 1, got 6" in scored["issues"][0]


@pytest.mark.parametrize("call,missing_field", [
    ({"arguments": {}}, "name"),
    ({"name": "get_my_team"}, "arguments"),
])
def test_incomplete_call_records_are_rejected(call, missing_field):
    with pytest.raises(ValueError, match=missing_field):
        scorers.score_arguments(
            make_case("get_my_team", {}), {"tool_calls": [call]},
        )


def test_unknown_expected_tool_does_not_skip_validation():
    case = make_case("unregistered_tool", {})
    saved_result = {"tool_calls": [
        make_call("unregistered_tool", {}),
    ]}

    assert scorers.score_arguments(case, saved_result) == {
        "score": 0, "issues": ["Unknown tool: unregistered_tool"],
    }


def test_validation_issues_do_not_include_raw_input():
    private_value = "private-test-value /private/test-path"
    saved_result = {"tool_calls": [make_call(
        "get_chip_values", {
            "horizon": 1, "private_field": private_value,
        },
    )]}

    scored = scorers.score_arguments(chip_case(), saved_result)

    assert scored["score"] == 0
    assert scored["issues"] == [
        "Validation error in get_chip_values (call 0)",
    ]
    assert private_value not in json.dumps(scored)
    assert "private_field" not in json.dumps(scored)


def test_scoring_does_not_change_inputs_and_results_are_json_safe():
    case = make_case("compare_players", {
        "element_ids": [411, 379], "horizon": 4,
    })
    saved_result = {"tool_calls": [make_call(
        "compare_players", {"element_ids": [379, 411]},
    )]}
    original_case = deepcopy(case)
    original_result = deepcopy(saved_result)

    for scorer in (
        scorers.score_tool_selection, scorers.score_arguments,
    ):
        scored = scorer(case, saved_result)
        assert scored["score"] == 1
        assert json.loads(json.dumps(scored)) == scored

    assert case == original_case
    assert saved_result == original_result
