"""Evaluation command checks with synthetic cases and no live requests."""

import json
import shlex
import shutil
import socket
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from fpl import cli
from fpl.agent import observability
from fpl.config import Settings
from fpl.evals import runner
from fpl.evals.records import load_cases


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Evaluation CLI tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


@pytest.fixture
def evaluation(tmp_path, monkeypatch):
    settings = Settings(
        entry_id=None,
        data_dir=tmp_path / "data",
        ollama_model="fixture-model",
        ollama_base_url="http://example.invalid/v1/",
        ollama_api_key="private-ollama-key",
        langfuse_secret_key="private-langfuse-key",
    )
    snapshot = tmp_path / "snapshots" / "frozen-snapshot"
    manifest = {
        "snapshot_id": snapshot.name,
        "season": "2026-27",
        "gw": 7,
        "files": {"database": {"sha256": "frozen-database-hash"}},
    }
    cases = [
        {
            "id": "bank", "snapshot_id": snapshot.name,
            "input": "What is my frozen bank balance?",
            "expected_tools": ["get_my_team"],
            "expected_arguments": {"get_my_team": {}},
        },
        {
            "id": "chip", "snapshot_id": snapshot.name,
            "input": "Can the frozen tool value my Wildcard?",
            "expected_tools": ["get_chip_values"],
            "expected_arguments": {
                "get_chip_values": {"horizon": 1, "model": "full"},
            },
        },
    ]
    dataset = tmp_path / "cases.jsonl"
    runner.save_results(cases, dataset)
    root = settings.data_dir / "evals" / "runs"
    runtime = SimpleNamespace(
        settings=settings, snapshot=snapshot, cases=cases,
        dataset=dataset, root=root, calls=[], fail_second=False,
        arguments=[
            "eval", "--cases", str(dataset),
            "--snapshot", str(snapshot), "--run-id", "test-run",
        ],
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "validate_snapshot", lambda path: manifest)
    monkeypatch.setattr(cli, "read_manifest", lambda path: manifest)
    monkeypatch.setattr(observability, "git_metadata", lambda: {
        "commit": "fixture-commit", "dirty": False,
    })
    monkeypatch.setattr(cli, "message_client", lambda message: [
        {"role": "system", "content": "Fixed local test prompt"},
        {"role": "user", "content": message},
    ])
    runtime.batch = MagicMock(wraps=cli.run_cases)
    monkeypatch.setattr(cli, "run_cases", runtime.batch)

    def fake_agent(
        supplied_settings, question, directory, tool_calls,
        run_id, case_id, trace_context,
    ):
        assert supplied_settings is settings
        assert directory == snapshot
        assert run_id == "test-run"
        saved_manifest = load_cases(root / "test-run-manifest.jsonl")
        assert saved_manifest[0]["case_count"] == len(cases)
        case = next(case for case in cases if case["id"] == case_id)
        assert question == case["input"]
        runtime.calls.append(case_id)
        trace_context["trace_id"] = f"trace-{case_id}"
        if runtime.fail_second and case_id == "chip":
            raise RuntimeError("private-failure-message")
        for name in case["expected_tools"]:
            tool_calls.append({
                "name": name,
                "arguments": case["expected_arguments"][name],
                "status": "completed",
            })
        return "Synthetic answer; no model was called."

    monkeypatch.setattr(runner, "agent_loop", fake_agent)
    return runtime


@pytest.mark.parametrize("fail_second", [False, True])
def test_eval_runs_once_and_saves_manifest_results_and_scores(
    evaluation, capsys, fail_second,
):
    evaluation.fail_second = fail_second

    cli.main(evaluation.arguments)

    evaluation.batch.assert_called_once_with(
        evaluation.settings, evaluation.cases,
        evaluation.root / "test-run.jsonl",
        snapshot_root=evaluation.snapshot.parent, run_id="test-run",
    )
    assert evaluation.calls == ["bank", "chip"]
    raw = load_cases(evaluation.root / "test-run.jsonl")
    scored = load_cases(evaluation.root / "test-run-scored.jsonl")
    manifest = load_cases(evaluation.root / "test-run-manifest.jsonl")
    assert len(raw) == len(scored) == 2
    assert len(manifest) == 1
    for record in raw + scored:
        assert record["run_id"] == "test-run"
        assert record["trace_id"] == f"trace-{record['case_id']}"
    assert all(set(record["scores"]) == {
        "tool_selection", "argument_validity", "numbers_validity",
        "teams_validity", "safety_validity",
    } for record in scored)
    assert raw[0]["status"] == "completed"
    assert scored[0]["scores"]["tool_selection"]["score"] == 1
    if fail_second:
        assert raw[1]["status"] == "error"
        assert raw[1]["error_type"] == "RuntimeError"
        assert scored[1]["scores"]["tool_selection"]["score"] == 0
    else:
        assert raw[1]["status"] == "completed"
    details = manifest[0]
    assert details["run_id"] == "test-run"
    assert details["run_kind"] == "evaluation"
    assert details["db_hash"] == "frozen-database-hash"
    assert details["model"] == "fixture-model"
    assert details["code_commit"] == "fixture-commit"
    assert details["dataset_hash"] == cli.calculate_file_sha256(
        evaluation.dataset,
    )
    assert details["case_count"] == 2
    assert details["prompt_file"] == "system-v3.md"
    assert details["creation_time"].endswith("+00:00")
    assert "Saved 2 records." in capsys.readouterr().out
    for path in evaluation.root.glob("*.jsonl"):
        text = path.read_text(encoding="utf-8")
        assert "private-ollama-key" not in text
        assert "private-langfuse-key" not in text
        assert "private-failure-message" not in text


@pytest.mark.parametrize("suffix", [
    ".jsonl", "-scored.jsonl", "-manifest.jsonl",
])
def test_existing_artifact_stops_evaluation_before_model_calls(
    evaluation, suffix,
):
    evaluation.root.mkdir(parents=True)
    existing = evaluation.root / f"test-run{suffix}"
    existing.write_text("original\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="Refusing to overwrite"):
        cli.main(evaluation.arguments)

    evaluation.batch.assert_not_called()
    assert evaluation.calls == []
    assert existing.read_text(encoding="utf-8") == "original\n"


@pytest.mark.parametrize("problem", [
    "empty", "duplicate-case", "wrong-snapshot", "invalid-run",
])
def test_invalid_evaluation_stops_before_model_calls(evaluation, problem):
    if problem == "invalid-run":
        evaluation.arguments[-1] = "../unsafe-run"
    else:
        cases = [dict(case) for case in evaluation.cases]
        if problem == "empty":
            cases = []
        elif problem == "duplicate-case":
            cases[1]["id"] = cases[0]["id"]
        else:
            cases[1]["snapshot_id"] = "another-snapshot"
        evaluation.dataset.write_text(
            "".join(json.dumps(case) + "\n" for case in cases),
            encoding="utf-8",
        )

    with pytest.raises(SystemExit):
        cli.main(evaluation.arguments)

    evaluation.batch.assert_not_called()
    assert evaluation.calls == []
    assert not evaluation.root.exists()


def test_metadata_failure_stops_without_exposing_exception_text(
    evaluation, monkeypatch,
):
    def fail(**kwargs):
        raise RuntimeError("private-ollama-key /private/test-path")

    monkeypatch.setattr(cli, "build_run_metadata", fail)
    with pytest.raises(SystemExit) as error:
        cli.main(evaluation.arguments)

    assert str(error.value) == "Failed to build run metadata (RuntimeError)."
    assert error.value.__suppress_context__
    evaluation.batch.assert_not_called()
    assert evaluation.calls == []
    assert list(evaluation.root.iterdir()) == []


@pytest.mark.parametrize("arguments", [
    ["eval", "--snapshot", "snapshot", "--run-id", "run"],
    ["eval", "--cases", "cases", "--run-id", "run"],
    ["eval", "--cases", "cases", "--snapshot", "snapshot"],
    ["eval", "--help"],
])
def test_eval_help_and_missing_arguments_do_not_load_settings(
    monkeypatch, arguments,
):
    settings = MagicMock(side_effect=AssertionError("Settings loaded"))
    monkeypatch.setattr(cli, "load_settings", settings)

    with pytest.raises(SystemExit) as result:
        cli.main(arguments)

    assert result.value.code == (0 if "--help" in arguments else 2)
    settings.assert_not_called()


def test_make_recipe_uses_supported_flags_and_provider_environment():
    make = shutil.which("make")
    if make is None:
        pytest.skip("make is not installed")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            make, "-n", "eval-baseline", "FPL=fpl",
            "EVAL_DATASET=fixture-cases.jsonl",
            "EVAL_SNAPSHOT=fixture-snapshot", "EVAL_RUN=fixture-run",
            "EVAL_OLLAMA_MODEL=fixture-model",
            "EVAL_ENDPOINT=http://example.invalid/v1/",
        ],
        cwd=root, capture_output=True, text=True, check=True,
    )
    assert shlex.split(result.stdout.replace("\\\n", " ")) == [
        "OLLAMA_MODEL=fixture-model",
        "OLLAMA_BASE_URL=http://example.invalid/v1/",
        "fpl", "eval", "--cases", "fixture-cases.jsonl",
        "--snapshot", "data/evals/snapshots/fixture-snapshot",
        "--run-id", "fixture-run",
    ]


def test_rescore_scores_a_saved_run_without_model_calls(evaluation, capsys):
    calls = [
        ("get_my_team", {}, {"bank_in_tenths": 10}, "You have £1.0m."),
        ("get_chip_values", {"horizon": 1, "model": "full"}, {},
         "It adds 10.0 points."),
    ]
    records = [
        {
            "case_id": case["id"], "snapshot_id": case["snapshot_id"],
            "input": case["input"], "answer": answer, "status": "completed",
            "tool_calls": [{"name": name, "arguments": arguments,
                            "status": "completed", "result": result}],
        }
        for case, (name, arguments, result, answer)
        in zip(evaluation.cases, calls)
    ]
    runner.save_results(records, evaluation.root / "test-run.jsonl")

    cli.main(["rescore", "--cases", str(evaluation.dataset),
              "--run-id", "test-run"])

    rescored = load_cases(evaluation.root / "test-run-rescored.jsonl")
    assert [record["scores"]["numbers_validity"]["score"]
            for record in rescored] == [1, 0]
    assert capsys.readouterr().out == "numbers_validity: chip\n"
    assert evaluation.calls == []


@pytest.mark.parametrize(("run_id", "message"), [
    ("missing-run", "Run file not found"),
    ("test-run", "Refusing to overwrite"),
])
def test_rescore_refuses_a_missing_run_or_existing_output(
    evaluation, run_id, message,
):
    runner.save_results([], evaluation.root / "test-run.jsonl")
    existing = evaluation.root / "test-run-rescored.jsonl"
    existing.write_text("original\n", encoding="utf-8")

    with pytest.raises(SystemExit, match=message):
        cli.main(["rescore", "--cases", str(evaluation.dataset),
                  "--run-id", run_id])

    assert existing.read_text(encoding="utf-8") == "original\n"
