"""Offline behaviour checks for the user's Step 15 agent loop."""

import json
import socket
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletionMessage

from fpl.agent import loop, model, service
from fpl.agent.schemas import HistoricalLeadersInput, MyTeamInput
from fpl.config import Settings


def assistant_message(content=None, calls=None):
    """Build a real SDK message without contacting the model provider."""
    return ChatCompletionMessage(role="assistant", content=content, tool_calls=calls)


def tool_call(call_id="call_1", name="get_my_team", arguments="{}"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Agent loop tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """Replace model and tool execution, but retain real argument validation."""
    settings = Settings(entry_id=None, data_dir=tmp_path)
    snapshot_dir = tmp_path / "chosen-snapshot"
    executions = []
    responses = []
    requests = []
    tools = [{
        "type": "function",
        "function": {
            "name": "get_my_team",
            "description": "Read the frozen FPL squad and bank balance.",
            "parameters": MyTeamInput.model_json_schema(),
        },
    }]

    def fake_model(supplied_settings, messages, tools=None):
        assert supplied_settings is settings
        requests.append({"messages": deepcopy(messages), "tools": deepcopy(tools)})
        if not responses:
            raise AssertionError("Unexpected extra model request")
        return responses.pop(0)

    def fake_tool(directory, name, arguments):
        assert directory == snapshot_dir
        MyTeamInput.model_validate(arguments)
        executions.append({"name": name, "arguments": arguments})
        return SimpleNamespace(
            model_dump_json=lambda: json.dumps({"bank_in_tenths": 10})
        )

    monkeypatch.setattr(loop, "model_request", fake_model)
    monkeypatch.setattr(loop, "run_tool", fake_tool)
    monkeypatch.setattr(loop, "tool_definitions", lambda: deepcopy(tools))
    # Check file loading separately so a prompt bug does not mask loop behaviour.
    monkeypatch.setattr(loop, "message_client", lambda message: [
        {"role": "system", "content": "You assist with Fantasy Premier League."},
        {"role": "user", "content": message},
    ])
    return SimpleNamespace(
        settings=settings,
        snapshot_dir=snapshot_dir,
        responses=responses,
        requests=requests,
        executions=executions,
    )


def ask(runtime):
    return loop.agent_loop(
        runtime.settings, "How much is in my FPL bank?", runtime.snapshot_dir
    )


@pytest.mark.parametrize("calls", [None, []])
def test_final_answer_needs_no_tool_execution(runtime, calls):
    runtime.responses.append(assistant_message("Please clarify your question.", calls))

    assert ask(runtime) == "Please clarify your question."
    assert len(runtime.requests) == 1
    assert runtime.executions == []


def test_tool_result_is_returned_with_matching_call_id(runtime):
    runtime.responses.extend([
        assistant_message(calls=[tool_call("bank_call")]),
        assistant_message("Your remaining transfer budget is £1.0m."),
    ])

    assert ask(runtime) == "Your remaining transfer budget is £1.0m."
    assert runtime.executions == [{"name": "get_my_team", "arguments": {}}]
    assert len(runtime.requests) == 2
    messages = runtime.requests[1]["messages"]
    assert [message["role"] for message in messages] == [
        "system", "user", "assistant", "tool"
    ]
    assert messages[2]["tool_calls"][0]["id"] == "bank_call"
    assert messages[3]["tool_call_id"] == "bank_call"
    assert json.loads(messages[3]["content"]) == {"bank_in_tenths": 10}
    assert all(
        request["tools"][0]["function"]["name"] == "get_my_team"
        for request in runtime.requests
    )


def test_all_registered_tools_are_offered_and_another_tool_can_run(runtime, monkeypatch):
    definitions = service.tool_definitions()
    monkeypatch.setattr(loop, "tool_definitions", lambda: deepcopy(definitions))

    def historical_tool(directory, name, arguments):
        assert directory == runtime.snapshot_dir
        assert name == "get_historical_leaders"
        request = HistoricalLeadersInput.model_validate(arguments)
        assert request.gw == 4
        assert request.limit == 1
        runtime.executions.append({"name": name, "arguments": arguments})
        return SimpleNamespace(model_dump_json=lambda: json.dumps({
            "gw": 4,
            "leaders": [{"player_name": "Fixture Player", "value": 12}],
        }))

    monkeypatch.setattr(loop, "run_tool", historical_tool)
    runtime.responses.extend([
        assistant_message(calls=[tool_call(
            "leader_call", "get_historical_leaders", '{"gw": 4, "limit": 1}'
        )]),
        assistant_message("Fixture Player scored 12 points in GW4."),
    ])

    assert ask(runtime) == "Fixture Player scored 12 points in GW4."
    assert runtime.executions == [{
        "name": "get_historical_leaders", "arguments": {"gw": 4, "limit": 1},
    }]
    offered_names = {
        definition["function"]["name"] for definition in runtime.requests[0]["tools"]
    }
    assert offered_names == set(service.TOOL_REGISTRY)
    tool_result = runtime.requests[1]["messages"][-1]
    assert tool_result["role"] == "tool"
    assert tool_result["tool_call_id"] == "leader_call"
    assert json.loads(tool_result["content"])["leaders"][0]["value"] == 12


def test_another_tool_request_continues_the_same_history(runtime):
    runtime.responses.extend([
        assistant_message(calls=[tool_call("first")]),
        assistant_message(calls=[tool_call("second")]),
        assistant_message("You have £1.0m remaining."),
    ])

    assert ask(runtime) == "You have £1.0m remaining."
    assert len(runtime.requests) == 3
    assert len(runtime.executions) == 2
    tool_messages = [
        message for message in runtime.requests[2]["messages"]
        if message["role"] == "tool"
    ]
    assert [message["tool_call_id"] for message in tool_messages] == ["first", "second"]


def test_multiple_calls_receive_sequential_results(runtime):
    runtime.responses.extend([
        assistant_message(calls=[tool_call("first"), tool_call("second")]),
        assistant_message("You have £1.0m remaining."),
    ])

    assert ask(runtime) == "You have £1.0m remaining."
    assert len(runtime.executions) == 2
    tool_messages = [
        message for message in runtime.requests[1]["messages"]
        if message["role"] == "tool"
    ]
    assert [message["tool_call_id"] for message in tool_messages] == ["first", "second"]


def test_unoffered_tool_is_rejected_before_execution(runtime):
    runtime.responses.append(assistant_message(calls=[tool_call(name="execute_sql")]))

    with pytest.raises(ValueError):
        ask(runtime)
    assert runtime.executions == []
    assert len(runtime.requests) == 1


@pytest.mark.parametrize("arguments", ["{bad-json", "[]", '{"extra": true}'])
def test_invalid_arguments_stop_before_tool_execution(runtime, arguments):
    runtime.responses.append(assistant_message(calls=[tool_call(arguments=arguments)]))

    with pytest.raises(ValueError):
        ask(runtime)
    assert runtime.executions == []
    assert len(runtime.requests) == 1


def test_model_request_limit_is_four(runtime):
    runtime.responses.extend([
        assistant_message(calls=[tool_call(f"call_{index}")])
        for index in range(5)
    ])

    with pytest.raises(RuntimeError):
        ask(runtime)
    assert len(runtime.requests) == 4


def test_final_answer_on_fourth_request_is_allowed(runtime):
    runtime.responses.extend([
        assistant_message(calls=[tool_call(f"call_{index}")])
        for index in range(3)
    ])
    runtime.responses.append(assistant_message("You have £1.0m remaining."))

    assert ask(runtime) == "You have £1.0m remaining."
    assert len(runtime.requests) == 4
    assert len(runtime.executions) == 3


@pytest.mark.parametrize("content", [None, "", "   "])
def test_empty_final_response_is_an_error(runtime, content):
    runtime.responses.append(assistant_message(content))

    with pytest.raises(RuntimeError):
        ask(runtime)


def test_tool_failure_does_not_produce_a_fabricated_answer(runtime, monkeypatch):
    runtime.responses.append(assistant_message(calls=[tool_call()]))

    def failed_tool(*args, **kwargs):
        raise RuntimeError("Snapshot is unavailable")

    monkeypatch.setattr(loop, "run_tool", failed_tool)
    with pytest.raises(RuntimeError, match="Snapshot is unavailable"):
        ask(runtime)
    assert len(runtime.requests) == 1


def test_system_prompt_is_loaded_as_text_independent_of_working_directory(tmp_path, monkeypatch):
    prompt_path = Path(model.__file__).parent / "prompts" / "system-v1.md"
    prompt_text = prompt_path.read_text(encoding="utf-8").strip()
    monkeypatch.chdir(tmp_path)

    messages = model.message_client("My question")

    assert isinstance(messages[0]["content"], str)
    assert messages[0] == {"role": "system", "content": prompt_text}
    assert messages[1] == {"role": "user", "content": "My question"}
    assert not prompt_text.startswith("prompt =")
