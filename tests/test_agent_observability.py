"""Check tracing privacy, metadata and prompt references without network access."""

import hashlib
import json
import socket
from copy import deepcopy
from types import SimpleNamespace

import pytest

from fpl.agent import observability
from fpl.config import Settings


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Observability tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def test_message_filter_preserves_original_and_public_player_details():
    messages = [
        {"role": "user", "content": "Private Team: secret-long"},
        {"role": "assistant", "tool_calls": [{"function": {
            "name": "get_player_summary",
            "arguments": json.dumps({"entry_id": 1234567, "element_id": 109}),
        }}]},
        {"role": "tool", "content": json.dumps({
            "entry_id": 1234567, "team_name": "Private Team", "bank_in_tenths": 10,
            "players": [{"element_id": 109, "player_name": "Verbruggen",
                         "nested": {"team_name": "Private Team", "api_key": "secret-long"}}],
        })},
    ]
    original = deepcopy(messages)
    filtered = observability.sanitise_messages(
        messages, ("Private Team", "1234567", "secret", "secret-long"))

    assert messages == original
    assert filtered[0]["content"] == "[REDACTED]: [REDACTED]"
    arguments = json.loads(filtered[1]["tool_calls"][0]["function"]["arguments"])
    assert arguments == {"element_id": 109}
    result = json.loads(filtered[2]["content"])
    assert result["bank_in_tenths"] == 10
    assert result["players"][0]["player_name"] == "Verbruggen"
    assert result["players"][0]["element_id"] == 109
    assert result["players"][0]["nested"] == {}
    assert "1234567" not in json.dumps(filtered)
    assert "secret-long" not in json.dumps(filtered)


@pytest.mark.parametrize("content", ["{broken", "null", "42", None, 42, object()])
def test_unexpected_tool_content_has_a_safe_placeholder(content):
    filtered = observability.sanitise_messages([{"role": "tool", "content": content}])
    assert filtered[0]["content"].startswith("[filtered:")


def test_structured_tool_content_is_filtered():
    message = {"role": "tool", "content": {
        "entry_id": 1234567, "player": {"element_id": 109, "team_name": "Private Team"},
    }}
    filtered = observability.sanitise_messages([message])
    assert filtered[0]["content"] == {"player": {"element_id": 109}}
    assert message["content"]["entry_id"] == 1234567


def test_invalid_messages_and_tool_arguments_are_not_logged_raw():
    filtered = observability.sanitise_messages([
        "unexpected secret", {"role": "assistant", "content": None, "tool_calls": [
            {"function": {"name": "get_my_team", "arguments": "secret: broken JSON"}},
        ]},
    ])
    assert "unexpected secret" not in json.dumps(filtered)
    assert "secret: broken JSON" not in json.dumps(filtered)
    assert filtered[1]["content"] is None


def test_private_values_are_selected_without_redacting_public_squad_fields(tmp_path):
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "team.json").write_text(json.dumps({
        "entry_id": 1234567, "team_name": "Private Team",
        "squad": [{"name": "Verbruggen", "element": 109}],
    }), encoding="utf-8")
    settings = Settings(entry_id=1234567, data_dir=tmp_path,
                        ollama_api_key="ollama", langfuse_secret_key="lf-secret")
    private = observability.private_values_for_run(settings, snapshot)

    assert "1234567" in private
    assert "Private Team" in private
    assert "lf-secret" in private
    assert str(snapshot) in private
    assert "Verbruggen" not in private
    assert "109" not in private
    assert "ollama" not in private
    assert observability.sanitise_trace_data(f"See {snapshot}/team.json", private) == (
        "See [REDACTED]/team.json")


def test_missing_manifest_is_optional_for_trace_metadata(tmp_path, caplog):
    assert observability.read_trace_manifest(tmp_path) == {}
    assert "unavailable" in caplog.text
    assert str(tmp_path) not in caplog.text


def test_metadata_uses_current_git_revision_and_stable_hashes(monkeypatch):
    monkeypatch.setattr(observability, "git_metadata", lambda: {
        "commit": "current-code-commit", "dirty": True,
    })
    manifest = {"snapshot_id": "snapshot", "season": "2026-27", "gw": 6,
                "files": {"database": {"sha256": "database-digest"}},
                "git": {"commit": "snapshot-creation-commit"}}
    tools = [{"name": "get_my_team", "parameters": {"type": "object"}}]
    metadata = observability.build_run_metadata(
        manifest, "Actual system prompt", tools, "anonymous-session", "fixture-model",
        prompt_name="fpl-system", prompt_version=1,
    )
    reordered = [{"parameters": {"type": "object"}, "name": "get_my_team"}]
    same = observability.build_run_metadata(
        manifest, "Actual system prompt", reordered, "other-session", "fixture-model")
    changed = observability.build_run_metadata(
        manifest, "Changed system prompt", tools + [{"name": "another"}],
        "session", "fixture-model")

    assert metadata["code_commit"] == "current-code-commit"
    assert metadata["code_dirty"] == "true"
    assert metadata["db_hash"] == "database-digest"
    assert metadata["prompt_version"] == "1"
    assert metadata["prompt_hash"] == hashlib.sha256(b"Actual system prompt").hexdigest()
    assert metadata["prompt_hash"] == same["prompt_hash"]
    assert metadata["tools_hash"] == same["tools_hash"]
    assert metadata["prompt_hash"] != changed["prompt_hash"]
    assert metadata["tools_hash"] != changed["tools_hash"]
    assert all(isinstance(value, str) for value in metadata.values())


def test_unknown_git_state_is_not_reported_as_clean(monkeypatch):
    monkeypatch.setattr(observability, "git_metadata", lambda: {
        "commit": None, "dirty": None,
    })
    metadata = observability.build_run_metadata({}, "Prompt", [], "session", "model")
    assert metadata["code_commit"] == "unknown"
    assert metadata["code_dirty"] == "unknown"
    assert metadata["db_hash"] == "unknown"
    assert "case_id" not in metadata
    assert "run_id" not in metadata


def test_evaluation_metadata_includes_run_and_case_ids(monkeypatch):
    monkeypatch.setattr(observability, "git_metadata", lambda: {
        "commit": "test-commit", "dirty": False,
    })
    metadata = observability.build_run_metadata(
        {}, "Prompt", [], "test-run", "fixture-model",
        run_kind="evaluation", run_id="test-run", case_id="bank",
    )

    assert metadata["run_kind"] == "evaluation"
    assert metadata["run_id"] == "test-run"
    assert metadata["case_id"] == "bank"
    assert metadata["session_id"] == "test-run"
    assert all(isinstance(value, str) for value in metadata.values())


def test_matching_prompt_returns_the_reference_object(fake_langfuse):
    candidate = observability.get_matching_prompt(fake_langfuse, " Local system prompt\n")
    assert candidate is fake_langfuse.prompt
    assert fake_langfuse.prompt_calls == [{
        "name": "fpl-system", "version": 3, "type": "text",
        "max_retries": 0, "fetch_timeout_seconds": 2,
    }]


def test_prompt_mismatch_skips_link_without_logging_prompt_text(fake_langfuse, caplog):
    fake_langfuse.prompt.prompt = "Different private prompt"
    assert observability.get_matching_prompt(fake_langfuse, "Local system prompt") is None
    assert "skipping" in caplog.text
    assert "Different private prompt" not in caplog.text


def test_prompt_lookup_failure_skips_link_without_logging_error_data(fake_langfuse, caplog):
    fake_langfuse.prompt_error = RuntimeError("secret-token /private/path")
    assert observability.get_matching_prompt(fake_langfuse, "Local system prompt") is None
    assert "lookup failed" in caplog.text
    assert "secret-token" not in caplog.text
    assert "/private/path" not in caplog.text


def test_fallback_prompt_is_not_linked_to_a_real_version():
    candidate = SimpleNamespace(prompt="Local system prompt", is_fallback=True)
    assert observability.validate_prompt("Local system prompt", candidate) is None


def test_no_op_contexts_do_not_prepare_or_record_data(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("A disabled trace attempted SDK or payload work")

    monkeypatch.setattr(observability, "propagate_attributes", unexpected)
    with observability.safe_observation(None) as span:
        assert span is None
        observability.safe_update(span, unexpected)
        with observability.safe_attributes(None):
            pass
    assert observability.get_matching_prompt(None, "Prompt") is None
    observability.safe_flush(None)


def test_client_setup_does_not_authenticate_on_each_question(tmp_path, monkeypatch, fake_langfuse):
    settings = Settings(entry_id=None, data_dir=tmp_path,
                        langfuse_public_key="public", langfuse_secret_key="secret")
    monkeypatch.setattr(observability, "get_client", fake_langfuse.get_client)
    assert observability.get_tracing_client(settings) is fake_langfuse
    assert fake_langfuse.auth_count == 0


def test_smoke_test_loads_settings_authenticates_and_flushes(tmp_path, monkeypatch,
                                                           fake_langfuse, capsys):
    settings = Settings(entry_id=None, data_dir=tmp_path,
                        langfuse_public_key="public", langfuse_secret_key="secret")
    calls = []
    def load():
        calls.append("settings")
        return settings
    def get():
        assert calls == ["settings"]
        return fake_langfuse
    monkeypatch.setattr(observability, "load_settings", load)
    monkeypatch.setattr(observability, "get_client", get)

    observability.smoke_test()
    assert fake_langfuse.auth_count == 1
    assert fake_langfuse.flush_count == 1
    assert fake_langfuse.observations[0].parameters["name"] == "fpl.trace-smoke"
    assert fake_langfuse.observations[0].updates == [{
        "input": "hello", "output": "connection works",
    }]
    assert "verify" in capsys.readouterr().out


@pytest.mark.parametrize("operation", [
    "disabled", "credentials", "client", "auth", "unauthenticated",
    "observation.create", "observation.enter", "observation.update",
    "observation.exit", "flush",
])
def test_smoke_test_reports_failure_instead_of_succeeding(tmp_path, monkeypatch,
                                                        fake_langfuse, operation):
    settings = Settings(entry_id=None, data_dir=tmp_path,
                        langfuse_public_key="public", langfuse_secret_key="secret",
                        langfuse_tracing_enabled=operation != "disabled")
    if operation == "credentials":
        from dataclasses import replace
        settings = replace(settings, langfuse_secret_key="")
    elif operation == "unauthenticated":
        fake_langfuse.authenticated = False
    else:
        fake_langfuse.failures.add(operation)
    monkeypatch.setattr(observability, "load_settings", lambda: settings)
    monkeypatch.setattr(observability, "get_client", fake_langfuse.get_client)

    with pytest.raises(RuntimeError):
        observability.smoke_test()
