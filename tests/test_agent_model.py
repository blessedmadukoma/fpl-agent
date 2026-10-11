"""Exercise real model-request instrumentation with an in-memory API client."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai.types.chat import ChatCompletionMessage

from fpl.agent import model
from fpl.config import Settings


@pytest.mark.parametrize("usage", [
    None,
    SimpleNamespace(prompt_tokens=12, completion_tokens=5),
    SimpleNamespace(prompt_tokens=0, completion_tokens=0),
])
def test_generation_records_filtered_copies_and_real_usage(tmp_path, monkeypatch, fake_langfuse, usage):
    settings = Settings(entry_id=None, data_dir=tmp_path, ollama_model="fixture-model")
    messages = [
        {"role": "system", "content": "Local system prompt"},
        {"role": "user", "content": "Private Team: secret-token"},
        {"role": "tool", "content": '{"team_name":"Private Team","bank_in_tenths":10}'},
    ]
    tools = [{"type": "function", "function": {"name": "get_my_team"}}]
    original = deepcopy(messages)
    reply = ChatCompletionMessage(role="assistant", content="Private Team has £1.0m.",
                                  reasoning="Reasoning must not be recorded.")
    api = MagicMock()
    api.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=reply)], usage=usage)
    monkeypatch.setattr(model, "OpenAI", lambda **kwargs: api)

    returned = model.model_request(
        settings, fake_langfuse, messages, tools,
        private_values=("Private Team", "secret-token"),
    )
    assert returned is reply
    assert messages == original
    assert api.chat.completions.create.call_args.kwargs["messages"] is messages
    assert api.chat.completions.create.call_args.kwargs["tools"] is tools
    generation = fake_langfuse.observations[0]
    assert generation.parameters["model"] == "fixture-model"
    assert generation.parameters["as_type"] == "generation"
    recorded = {key: value for update in generation.updates for key, value in update.items()}
    assert recorded["input"]["messages"][1]["content"] == "[REDACTED]: [REDACTED]"
    assert "team_name" not in recorded["input"]["messages"][2]["content"]
    assert recorded["output"] == {"content": "[REDACTED] has £1.0m."}
    if usage is None:
        assert "usage_details" not in recorded
    else:
        assert recorded["usage_details"] == {
            "input": usage.prompt_tokens, "output": usage.completion_tokens,
        }
    assert generation.closed


def test_generation_keeps_tool_requests_without_leaking_private_arguments(tmp_path, monkeypatch, fake_langfuse):
    settings = Settings(entry_id=None, data_dir=tmp_path)
    reply = ChatCompletionMessage(role="assistant", content=None, tool_calls=[{
        "id": "call", "type": "function", "function": {
            "name": "get_player_summary", "arguments": '{"entry_id":1234567,"element_id":109}',
        },
    }])
    api = MagicMock()
    api.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=reply)], usage=None)
    monkeypatch.setattr(model, "OpenAI", lambda **kwargs: api)

    assert model.model_request(settings, fake_langfuse, []) is reply
    output = fake_langfuse.observations[0].updates[1]["output"]
    assert "content" not in output
    assert output["tool_calls"][0]["function"]["arguments"] == '{"element_id": 109}'
    assert reply.tool_calls[0].function.arguments == '{"entry_id":1234567,"element_id":109}'
