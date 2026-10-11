"""Offline behaviour and tracing checks for the FPL agent loop."""

import hashlib
import json
import socket
import uuid
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai.types.chat import ChatCompletionMessage
from pydantic import BaseModel

from fpl.agent import loop, model, observability, service
from fpl.agent.schemas import HistoricalLeadersInput, MyTeamInput
from fpl.config import Settings


class BankToolResult(BaseModel):
    bank_in_tenths: int


class HistoricalToolResult(BaseModel):
    gw: int
    leaders: list[dict[str, str | int]]


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
def runtime(tmp_path, monkeypatch, fake_langfuse):
    """Replace model and tool execution, but retain real argument validation."""
    settings = Settings(
        entry_id=None, data_dir=tmp_path, ollama_api_key="test-ollama-secret",
        langfuse_public_key="test-lf-public", langfuse_secret_key="test-lf-secret",
    )
    snapshot_dir = tmp_path / "chosen-snapshot"
    snapshot_dir.mkdir()
    manifest = {
        "schema_version": 1, "snapshot_id": "fixture-snapshot",
        "season": "2026-27", "gw": 6,
        "files": {"database": {"sha256": "fixture-database-hash"}},
    }
    (snapshot_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (snapshot_dir / "team.json").write_text(json.dumps({
        "team_name": "Private Team", "entry_id": 1234567,
    }), encoding="utf-8")
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

    def fake_model(supplied_settings, lf_client, messages, tools=None, private_values=()):
        assert supplied_settings is settings
        assert lf_client is None or lf_client is fake_langfuse
        requests.append({"messages": deepcopy(
            messages), "tools": deepcopy(tools)})
        if not responses:
            raise AssertionError("Unexpected extra model request")
        return responses.pop(0)

    def fake_tool(directory, name, arguments):
        assert directory == snapshot_dir
        MyTeamInput.model_validate(arguments)
        executions.append({"name": name, "arguments": arguments})
        return BankToolResult(bank_in_tenths=10)

    monkeypatch.setattr(loop, "model_request", fake_model)
    monkeypatch.setattr(loop, "run_tool", fake_tool)
    monkeypatch.setattr(loop, "tool_definitions", lambda: deepcopy(tools))
    monkeypatch.setattr(observability, "get_client", fake_langfuse.get_client)
    monkeypatch.setattr(observability, "propagate_attributes", fake_langfuse.propagate_attributes)
    fake_langfuse.prompt.prompt = "You assist with Fantasy Premier League."
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
        langfuse=fake_langfuse,
        manifest=manifest,
    )


def ask(runtime):
    return loop.agent_loop(
        runtime.settings, "How much is in my FPL bank?", runtime.snapshot_dir
    )


@pytest.mark.parametrize("calls", [None, []])
def test_final_answer_needs_no_tool_execution(runtime, calls):
    runtime.responses.append(assistant_message(
        "Please clarify your question.", calls))

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
    monkeypatch.setattr(loop, "tool_definitions",
                        lambda: deepcopy(definitions))

    def historical_tool(directory, name, arguments):
        assert directory == runtime.snapshot_dir
        assert name == "get_historical_leaders"
        request = HistoricalLeadersInput.model_validate(arguments)
        assert request.gw == 4
        assert request.limit == 1
        runtime.executions.append({"name": name, "arguments": arguments})
        return HistoricalToolResult(
            gw=4,
            leaders=[{"player_name": "Fixture Player", "value": 12}],
        )

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
    assert [message["tool_call_id"]
            for message in tool_messages] == ["first", "second"]


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
    assert [message["tool_call_id"]
            for message in tool_messages] == ["first", "second"]


def test_unoffered_tool_is_rejected_before_execution(runtime):
    runtime.responses.append(assistant_message(
        calls=[tool_call(name="execute_sql")]))

    with pytest.raises(ValueError):
        ask(runtime)
    assert runtime.executions == []
    assert len(runtime.requests) == 1


@pytest.mark.parametrize("arguments", ["{bad-json", "[]", '{"extra": true}'])
def test_invalid_arguments_stop_before_tool_execution(runtime, arguments):
    runtime.responses.append(assistant_message(
        calls=[tool_call(arguments=arguments)]))

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


def test_complete_trace_links_matching_prompt_and_filters_only_recorded_data(runtime, monkeypatch):
    class SensitiveBankResult(BankToolResult):
        team_name: str
        entry_id: int
        player_name: str

    def private_tool(directory, name, arguments):
        return SensitiveBankResult(bank_in_tenths=10, team_name="Private Team",
                                   entry_id=1234567, player_name="Verbruggen")

    question = "Private Team test-lf-secret"
    answer = "Private Team has £1.0m. test-lf-secret"
    replies = [assistant_message(calls=[tool_call("bank_call")]), assistant_message(answer)]
    captured = []
    api = MagicMock()

    def create(**kwargs):
        captured.append(deepcopy(kwargs))
        return SimpleNamespace(choices=[SimpleNamespace(message=replies.pop(0))], usage=None)

    api.chat.completions.create.side_effect = create
    monkeypatch.setattr(model, "OpenAI", lambda **kwargs: api)
    monkeypatch.setattr(loop, "model_request", model.model_request)
    monkeypatch.setattr(loop, "run_tool", private_tool)

    assert loop.agent_loop(runtime.settings, question, str(runtime.snapshot_dir)) == answer
    observations = runtime.langfuse.observations
    assert [item.parameters["as_type"] for item in observations] == [
        "span", "generation", "tool", "generation"]
    root = observations[0]
    assert all(item.parent is root for item in observations[1:])
    assert all(item.closed for item in observations)
    metadata = next(update["metadata"] for update in root.updates if "metadata" in update)
    local_prompt = "You assist with Fantasy Premier League."
    assert metadata["prompt_hash"] == hashlib.sha256(local_prompt.encode()).hexdigest()
    assert metadata["prompt_hash"] != hashlib.sha256(question.encode()).hexdigest()
    assert metadata["snapshot_id"] == runtime.manifest["snapshot_id"]
    assert metadata["db_hash"] == "fixture-database-hash"
    assert metadata["prompt_name"] == "fpl-system"
    assert metadata["prompt_version"] == "1"
    assert str(uuid.UUID(root.attributes["session_id"])) == metadata["session_id"]
    for generation in (observations[1], observations[3]):
        assert generation.attributes["prompt"] is runtime.langfuse.prompt
        assert generation.attributes["session_id"] == metadata["session_id"]

    assert captured[0]["messages"][0]["content"] == local_prompt
    assert captured[0]["messages"][1]["content"] == question
    original_tool_data = json.loads(captured[1]["messages"][-1]["content"])
    assert original_tool_data["team_name"] == "Private Team"
    assert original_tool_data["entry_id"] == 1234567
    recorded_io = [
        update[key] for observation in observations for update in observation.updates
        for key in ("input", "output") if key in update
    ]
    encoded = json.dumps(recorded_io)
    assert "Private Team" not in encoded
    assert "test-lf-secret" not in encoded
    assert "1234567" not in encoded
    assert "Verbruggen" in encoded
    assert len(runtime.langfuse.prompt_calls) == 1
    assert runtime.langfuse.flush_count == 1


@pytest.mark.parametrize("failure", ["mismatch", "lookup"])
def test_unmatched_prompt_does_not_change_local_inference(runtime, failure):
    if failure == "mismatch":
        runtime.langfuse.prompt.prompt = "An unrelated prompt"
    else:
        runtime.langfuse.prompt_error = RuntimeError("Prompt service unavailable")
    runtime.responses.append(assistant_message("Answer from the local prompt"))

    assert ask(runtime) == "Answer from the local prompt"
    assert runtime.requests[0]["messages"][0]["content"] == (
        "You assist with Fantasy Premier League.")
    root = runtime.langfuse.observations[0]
    assert root.attributes["prompt"] is None
    metadata = next(update["metadata"] for update in root.updates if "metadata" in update)
    assert metadata["prompt_version"] == "unknown"
    assert len(runtime.langfuse.prompt_calls) == 1
    assert len(runtime.requests) == 1
    assert runtime.langfuse.flush_count == 1


def mock_ollama(monkeypatch, replies):
    api = MagicMock()
    api.chat.completions.create.side_effect = [
        SimpleNamespace(choices=[SimpleNamespace(message=reply)], usage=None)
        for reply in replies
    ]
    monkeypatch.setattr(model, "OpenAI", lambda **kwargs: api)
    monkeypatch.setattr(loop, "model_request", model.model_request)
    return api


@pytest.mark.parametrize(("operation", "as_type"), [
    ("client", None),
    *[(f"observation.{stage}", kind)
      for stage in ("create", "enter", "update", "exit")
      for kind in ("span", "generation", "tool")],
    ("attributes.create", None), ("attributes.enter", None),
    ("attributes.exit", None), ("flush", None),
])
def test_tracing_faults_do_not_change_or_repeat_agent_work(runtime, monkeypatch, caplog,
                                                          operation, as_type):
    runtime.langfuse.failures.add(operation)
    runtime.langfuse.fail_as_type = as_type
    api = mock_ollama(monkeypatch, [
        assistant_message(calls=[tool_call("bank")]),
        assistant_message("Your remaining transfer budget is £1.0m."),
    ])

    assert ask(runtime) == "Your remaining transfer budget is £1.0m."
    assert api.chat.completions.create.call_count == 2
    assert len(runtime.executions) == 1
    assert runtime.langfuse.active == []
    assert caplog.records
    assert "test-lf-secret" not in caplog.text
    assert "/private/path" not in caplog.text
    if operation == "client" or (as_type == "span" and operation in {
        "observation.create", "observation.enter",
    }):
        assert runtime.langfuse.prompt_calls == []
        assert not any(item.parent is not None for item in runtime.langfuse.observations)


@pytest.mark.parametrize("setting", [
    {"langfuse_tracing_enabled": False},
    {"langfuse_public_key": ""},
    {"langfuse_secret_key": ""},
])
def test_disabled_or_unconfigured_tracing_never_contacts_langfuse(runtime, monkeypatch, setting):
    settings = replace(runtime.settings, **setting)
    getter = MagicMock(side_effect=AssertionError("Langfuse initialised unexpectedly"))
    monkeypatch.setattr(observability, "get_client", getter)
    api = mock_ollama(monkeypatch, [assistant_message("Answer without tracing")])

    assert loop.agent_loop(settings, "Question", runtime.snapshot_dir) == "Answer without tracing"
    getter.assert_not_called()
    assert api.chat.completions.create.call_count == 1
    assert runtime.langfuse.observations == []
    assert runtime.langfuse.prompt_calls == []
    assert runtime.langfuse.flush_count == 0


@pytest.mark.parametrize("function", [
    "private_values_for_run", "build_run_metadata", "sanitise_messages", "sanitise_trace_data",
])
def test_tracing_preparation_failure_does_not_block_answer(runtime, monkeypatch, caplog, function):
    def failed(*args, **kwargs):
        raise RuntimeError("test-lf-secret /private/path")

    if function == "private_values_for_run":
        target = loop
    elif function == "sanitise_messages":
        target = model
    elif function == "build_run_metadata":
        target = observability
    else:
        target = model
        monkeypatch.setattr(loop, function, failed)
    monkeypatch.setattr(target, function, failed)
    api = mock_ollama(monkeypatch, [assistant_message("Original answer")])

    assert ask(runtime) == "Original answer"
    assert api.chat.completions.create.call_count == 1
    assert "test-lf-secret" not in caplog.text
    assert "/private/path" not in caplog.text


@pytest.mark.parametrize("source", ["model", "tool"])
def test_original_business_error_survives_cleanup_and_flush_failures(runtime, monkeypatch,
                                                                    caplog, source):
    error = RuntimeError("private application details test-lf-secret")
    runtime.langfuse.failures.update({"observation.exit", "flush"})
    api = mock_ollama(monkeypatch, [assistant_message(calls=[tool_call()])])
    if source == "model":
        api.chat.completions.create.side_effect = error
    else:
        def failed_tool(*args, **kwargs):
            runtime.executions.append({"name": "failed-tool"})
            raise error
        monkeypatch.setattr(loop, "run_tool", failed_tool)

    with pytest.raises(RuntimeError) as failure:
        ask(runtime)
    assert failure.value is error
    assert api.chat.completions.create.call_count == 1
    assert len(runtime.executions) == (1 if source == "tool" else 0)
    root = runtime.langfuse.observations[0]
    assert {"level": "ERROR", "status_message": "RuntimeError"} in root.updates
    assert all(item.exit_arguments == (None, None, None)
               for item in runtime.langfuse.observations)
    assert "private application details" not in caplog.text
    assert "test-lf-secret" not in caplog.text
    assert runtime.langfuse.flush_count == 1
