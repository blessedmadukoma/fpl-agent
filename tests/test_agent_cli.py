"""Check fpl ask argument handling and output without contacting Ollama."""

from pathlib import Path

import pytest

from fpl import cli
from fpl.agent import loop
from fpl.config import Settings


def test_ask_passes_question_snapshot_and_settings_to_loop(tmp_path, monkeypatch, capsys):
    settings = Settings(entry_id=None, data_dir=tmp_path)
    snapshot = tmp_path / "chosen-snapshot"
    calls = []
    answer = "As of 7 October 2026, for GW6, your FPL bank is £1.0m."

    def fake_loop(supplied_settings, question, snapshot_dir):
        calls.append((supplied_settings, question, snapshot_dir))
        return answer

    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(loop, "agent_loop", fake_loop)

    cli.main(["ask", "How much is in my FPL bank?", "--snapshot", str(snapshot)])

    assert calls == [(settings, "How much is in my FPL bank?", snapshot)]
    assert isinstance(calls[0][2], Path)
    assert capsys.readouterr().out == answer + "\n"


@pytest.mark.parametrize("arguments", [
    ["ask", "How much is in my FPL bank?"],
    ["ask", "--snapshot", "chosen-snapshot"],
])
def test_ask_requires_question_and_snapshot_before_loading_settings(arguments, monkeypatch):
    def unexpected_load():
        raise AssertionError("Settings loaded before required arguments were checked")

    def unexpected_loop(*args, **kwargs):
        raise AssertionError("Model loop ran without the required arguments")

    monkeypatch.setattr(cli, "load_settings", unexpected_load)
    monkeypatch.setattr(loop, "agent_loop", unexpected_loop)

    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2


def test_ask_help_does_not_load_settings_or_call_model(monkeypatch, capsys):
    def unexpected_load():
        raise AssertionError("Help should not load settings")

    monkeypatch.setattr(cli, "load_settings", unexpected_load)
    with pytest.raises(SystemExit) as result:
        cli.main(["ask", "--help"])

    assert result.value.code == 0
    output = capsys.readouterr().out
    assert "question" in output
    assert "--snapshot" in output
