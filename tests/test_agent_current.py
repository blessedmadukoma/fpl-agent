"""Test fresh-snapshot preparation and Make shortcuts without live requests."""

import json
import shlex
import shutil
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fpl import cli
from fpl.agent import current, loop
from fpl.config import Settings


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Preparation tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


@pytest.fixture
def preparation(tmp_path, monkeypatch):
    settings = Settings(entry_id=123, data_dir=tmp_path)
    runtime = SimpleNamespace(
        settings=settings, events=[], connection=object(),
        ctx=object(), team=object(),
        client=SimpleNamespace(saved_raw_paths=(tmp_path / "raw.json.gz",)),
        summary={"finished_gws": [1, 2], "next_gw": 3},
        snapshot={"final_path": str(tmp_path / "new-snapshot")},
    )

    @contextmanager
    def connect(supplied_settings):
        assert supplied_settings is settings
        runtime.events.append("open")
        try:
            yield runtime.connection
        finally:
            runtime.events.append("close")

    def stub(name, value):
        def call(*args, **kwargs):
            runtime.events.append(name)
            return value
        return Mock(side_effect=call)

    monkeypatch.setattr(current, "connect", connect)
    monkeypatch.setattr(current, "FplClient", Mock(return_value=runtime.client))
    monkeypatch.setattr(current, "update_current", stub("update", runtime.summary))
    monkeypatch.setattr(current, "ensure_history", stub("history", None))
    monkeypatch.setattr(current, "load_odds", stub("odds", None))
    monkeypatch.setattr(
        current, "current_team", stub("team", (runtime.ctx, runtime.team)),
    )
    monkeypatch.setattr(
        current, "create_snapshot", stub("snapshot", runtime.snapshot),
    )
    return runtime


def test_preparation_refreshes_then_closes_database_before_copy(preparation):
    runtime = preparation

    result = current.prepare_current_snapshot(runtime.settings, "test-ask")

    assert result == runtime.snapshot
    assert runtime.events == [
        "open", "update", "history", "odds", "team", "close", "snapshot",
    ]
    current.update_current.assert_called_once_with(
        runtime.client, runtime.connection,
    )
    current.ensure_history.assert_called_once_with(
        runtime.settings, runtime.connection, [1, 2],
    )
    current.load_odds.assert_called_once_with(
        runtime.settings, runtime.connection, runtime.settings.current_season,
    )
    current.current_team.assert_called_once_with(
        runtime.connection, runtime.client, 123,
    )
    current.create_snapshot.assert_called_once_with(
        runtime.ctx, runtime.settings, name="test-ask", team=runtime.team,
        update_summary=runtime.summary, raw_paths=runtime.client.saved_raw_paths,
    )


@pytest.mark.parametrize("step", [
    "update_current", "ensure_history", "load_odds", "current_team",
])
def test_preparation_failure_closes_connection_and_does_not_freeze(
    preparation, step,
):
    getattr(current, step).side_effect = RuntimeError("Synthetic failure")

    with pytest.raises(RuntimeError, match="Synthetic failure"):
        current.prepare_current_snapshot(preparation.settings)

    assert preparation.events[-1] == "close"
    current.create_snapshot.assert_not_called()


def test_missing_entry_stops_before_any_download(preparation):
    settings = Settings(entry_id=None, data_dir=preparation.settings.data_dir)

    with pytest.raises(ValueError, match="FPL_ENTRY_ID"):
        current.prepare_current_snapshot(settings)

    current.FplClient.assert_not_called()
    assert preparation.events == []


def test_ask_current_uses_exact_new_snapshot_path(
    preparation, monkeypatch, capsys,
):
    runtime = preparation
    events = []
    prepare = Mock(return_value=runtime.snapshot)
    agent = Mock(side_effect=lambda *args: events.append("ask") or "Answer.")
    monkeypatch.setattr(cli, "load_settings", lambda: runtime.settings)
    monkeypatch.setattr(current, "prepare_current_snapshot", prepare)
    monkeypatch.setattr(loop, "agent_loop", agent)
    monkeypatch.setattr(
        cli.report, "print_snapshot", lambda value: events.append("report"),
    )

    cli.main(["ask-current", "My question?", "--name", "custom-ask"])

    prepare.assert_called_once_with(runtime.settings, "custom-ask")
    agent.assert_called_once_with(
        runtime.settings, "My question?", Path(runtime.snapshot["final_path"]),
    )
    assert events == ["report", "ask"]
    assert capsys.readouterr().out == "Answer.\n"


def test_ask_current_does_not_call_model_when_preparation_fails(
    preparation, monkeypatch,
):
    monkeypatch.setattr(cli, "load_settings", lambda: preparation.settings)
    prepare = Mock(side_effect=RuntimeError("Synthetic preparation failure"))
    agent = Mock()
    monkeypatch.setattr(current, "prepare_current_snapshot", prepare)
    monkeypatch.setattr(loop, "agent_loop", agent)

    with pytest.raises(RuntimeError, match="preparation failure"):
        cli.main(["ask-current", "My question?"])

    agent.assert_not_called()


def test_ask_current_rejects_empty_question_before_downloads(
    preparation, monkeypatch,
):
    monkeypatch.setattr(cli, "load_settings", lambda: preparation.settings)

    with pytest.raises(SystemExit, match="non-empty question"):
        cli.main(["ask-current", "  "])

    current.FplClient.assert_not_called()


@pytest.mark.parametrize("arguments", [["ask-current"], ["ask-current", "--help"]])
def test_ask_current_argument_checks_do_not_load_settings(monkeypatch, arguments):
    settings = Mock(side_effect=AssertionError("Settings should not load"))
    monkeypatch.setattr(cli, "load_settings", settings)

    with pytest.raises(SystemExit) as result:
        cli.main(arguments)

    assert result.value.code == (0 if "--help" in arguments else 2)
    settings.assert_not_called()


@pytest.mark.parametrize("reuse_snapshot", [False, True])
def test_make_ask_preserves_question_and_selects_requested_workflow(
    tmp_path, reuse_snapshot,
):
    make = shutil.which("make")
    if make is None:
        pytest.skip("make is not installed")
    stub = tmp_path / "fake_fpl.py"
    stub.write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8",
    )
    question = 'Compare "Haaland" and Isak\'s form; do not guess.'
    arguments = [
        make, "--no-print-directory", "ask",
        f"FPL={shlex.quote(sys.executable)} {shlex.quote(str(stub))}",
        f"QUESTION={question}",
        "HORIZON=3",
    ]
    if reuse_snapshot:
        arguments.append("SNAPSHOT=chosen snapshot")

    result = subprocess.run(
        arguments, cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, check=True,
    )

    expected = ["ask-current", question, "--horizon", "3"]
    if reuse_snapshot:
        expected = [
            "ask", question, "--snapshot", "chosen snapshot", "--horizon", "3",
        ]
    assert json.loads(result.stdout) == expected


def test_make_ask_default_question_uses_horizon_not_a_fixed_gameweek(tmp_path):
    make = shutil.which("make")
    if make is None:
        pytest.skip("make is not installed")
    stub = tmp_path / "fake_fpl.py"
    stub.write_text(
        "import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8",
    )

    result = subprocess.run(
        [make, "--no-print-directory", "ask", "HORIZON=3",
         f"FPL={shlex.quote(sys.executable)} {shlex.quote(str(stub))}"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, check=True,
    )

    assert json.loads(result.stdout) == [
        "ask-current",
        "What is my recommended action for the upcoming gameweek?",
        "--horizon", "3",
    ]


def test_ask_current_passes_numeric_horizon_to_agent(preparation, monkeypatch):
    runtime = preparation
    monkeypatch.setattr(cli, "load_settings", lambda: runtime.settings)
    monkeypatch.setattr(
        current, "prepare_current_snapshot", Mock(return_value=runtime.snapshot),
    )
    monkeypatch.setattr(cli.report, "print_snapshot", Mock())
    agent = Mock(return_value="Answer.")
    monkeypatch.setattr(loop, "agent_loop", agent)

    cli.main(["ask-current", "My question?", "--horizon", "3"])

    agent.assert_called_once_with(
        runtime.settings, "My question?", Path(runtime.snapshot["final_path"]),
        horizon=3,
    )
