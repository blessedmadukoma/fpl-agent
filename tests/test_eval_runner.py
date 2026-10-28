"""Runner checks with synthetic records and no live agent calls."""

import json
import socket
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fpl.config import Settings
from fpl.evals import runner


@pytest.fixture(autouse=True)
def no_live_execution(monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError("Runner tests must not use the network")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)
    monkeypatch.setattr(
        runner, "agent_loop", MagicMock(side_effect=reject),
    )


@pytest.fixture
def cases():
    return [
        {
            "id": "bank",
            "snapshot_id": "frozen-snapshot",
            "input": "How much is in my FPL bank?",
            "expected_tools": ["get_my_team"],
            "expected_arguments": {"get_my_team": {}},
        },
        {
            "id": "chip",
            "snapshot_id": "frozen-snapshot",
            "input": "Can the tool value my Wildcard in GW6?",
            "expected_tools": ["get_chip_values"],
            "expected_arguments": {
                "get_chip_values": {"horizon": 1, "model": "full"},
            },
        },
    ]


def make_call(name, arguments):
    return {
        "tool_call_id": "test-call",
        "name": name,
        "raw_arguments": json.dumps(arguments),
        "arguments": arguments,
        "status": "completed",
    }


@pytest.fixture
def saved_results(cases):
    calls = [
        make_call("get_my_team", {}),
        make_call("get_chip_values", {"horizon": 6, "model": "full"}),
    ]
    return [
        {
            "case_id": case["id"],
            "snapshot_id": case["snapshot_id"],
            "input": case["input"],
            "answer": "Synthetic answer",
            "status": "completed",
            "tool_calls": [call],
        }
        for case, call in zip(cases, calls)
    ]


@pytest.fixture
def scored_results(cases, saved_results):
    return runner.score_results(cases, saved_results)


@pytest.fixture
def reviews():
    # Review order differs from result order to check the ID matching.
    return [
        {
            "case_id": "chip",
            "run_id": "test-run",
            "scores": {
                "fact_recall": {"score": 0},
                "groundedness": {"score": 0},
                "task_success": {"score": 0},
            },
            "primary_cause": "unsupported claim",
            "note": "Synthetic unsupported chip claim.",
        },
        {
            "case_id": "bank",
            "run_id": "test-run",
            "scores": {
                "fact_recall": {"score": 1},
                "groundedness": {"score": 1},
                "task_success": {"score": 1},
            },
            "primary_cause": None,
            "note": "Synthetic correct bank answer.",
        },
    ]


def test_load_cases_reads_unicode_and_ignores_blank_lines(tmp_path):
    path = tmp_path / "cases.jsonl"
    expected = [{"id": "one", "input": "Groß"}, {"id": "two"}]
    text = "\n\n".join(
        json.dumps(record, ensure_ascii=False) for record in expected
    )
    path.write_text("\n" + text + "\n\n", encoding="utf-8")

    assert runner.load_cases(path) == expected


def test_load_cases_rejects_malformed_json(tmp_path):
    path = tmp_path / "invalid.jsonl"
    path.write_text("{\n", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        runner.load_cases(path)


def test_run_case_records_evaluation_context_and_selected_snapshot(
    cases, tmp_path, monkeypatch,
):
    settings = Settings(entry_id=None, data_dir=tmp_path)
    snapshot_root = tmp_path / "snapshots"
    call = make_call("get_my_team", {})

    def fake_agent(
        actual_settings, question, snapshot, tool_calls,
        run_id, case_id, trace_context,
    ):
        assert actual_settings is settings
        assert question == cases[0]["input"]
        assert snapshot == snapshot_root / cases[0]["snapshot_id"]
        assert run_id == "test-run"
        assert case_id == cases[0]["id"]
        assert trace_context == {"trace_id": None}
        trace_context["trace_id"] = "synthetic-trace"
        tool_calls.append(call)
        return "You have £1.0m."

    monkeypatch.setattr(runner, "agent_loop", fake_agent)

    assert runner.run_case(
        settings, cases[0], snapshot_root, run_id="test-run",
    ) == {
        "case_id": "bank",
        "run_id": "test-run",
        "trace_id": "synthetic-trace",
        "snapshot_id": "frozen-snapshot",
        "input": cases[0]["input"],
        "answer": "You have £1.0m.",
        "status": "completed",
        "tool_calls": [call],
    }


def test_run_case_keeps_partial_calls_but_not_exception_text(
    cases, tmp_path, monkeypatch,
):
    settings = Settings(entry_id=None, data_dir=tmp_path)
    call = make_call("get_my_team", {})

    def failing_agent(
        settings, question, snapshot, tool_calls,
        run_id, case_id, trace_context,
    ):
        assert run_id == "test-run"
        assert case_id == cases[0]["id"]
        trace_context["trace_id"] = "failed-trace"
        tool_calls.append(call)
        raise RuntimeError("private-test-value /private/test-path")

    monkeypatch.setattr(runner, "agent_loop", failing_agent)
    result = runner.run_case(settings, cases[0], run_id="test-run")

    assert result["status"] == "error"
    assert result["answer"] is None
    assert result["error_type"] == "RuntimeError"
    assert result["tool_calls"] == [call]
    assert result["run_id"] == "test-run"
    assert result["trace_id"] == "failed-trace"
    assert "private-test-value" not in json.dumps(result)
    assert "/private/test-path" not in json.dumps(result)


def test_run_case_uses_a_fresh_collector(cases, tmp_path, monkeypatch):
    settings = Settings(entry_id=None, data_dir=tmp_path)
    collectors = []
    trace_contexts = []

    def fake_agent(
        settings, question, snapshot, tool_calls,
        run_id, case_id, trace_context,
    ):
        assert tool_calls == []
        assert trace_context == {"trace_id": None}
        collectors.append(tool_calls)
        trace_contexts.append(trace_context)
        trace_context["trace_id"] = f"trace-{len(trace_contexts)}"
        tool_calls.append(make_call("get_my_team", {}))
        return "Synthetic answer"

    monkeypatch.setattr(runner, "agent_loop", fake_agent)
    runner.run_case(settings, cases[0])
    runner.run_case(settings, cases[0])

    assert collectors[0] is not collectors[1]
    assert trace_contexts[0] is not trace_contexts[1]
    assert trace_contexts[0]["trace_id"] == "trace-1"
    assert trace_contexts[1]["trace_id"] == "trace-2"


def test_run_case_without_tracing_keeps_null_trace_id(
    cases, tmp_path, monkeypatch,
):
    settings = Settings(entry_id=None, data_dir=tmp_path)
    fake_agent = MagicMock(return_value="Answer without tracing")
    monkeypatch.setattr(runner, "agent_loop", fake_agent)

    result = runner.run_case(settings, cases[0])

    assert result["status"] == "completed"
    assert result["run_id"] is None
    assert result["trace_id"] is None
    assert fake_agent.call_args.kwargs["case_id"] == cases[0]["id"]


def test_batch_saves_before_next_case_and_continues_after_failure(
    cases, tmp_path, monkeypatch,
):
    settings = Settings(entry_id=None, data_dir=tmp_path)
    destination = tmp_path / "results" / "run.jsonl"
    questions = []

    def fake_agent(
        settings, question, snapshot, tool_calls,
        run_id, case_id, trace_context,
    ):
        if questions:
            assert len(runner.load_cases(destination)) == 1
        assert run_id == "test-run"
        trace_context["trace_id"] = f"trace-{case_id}"
        questions.append(question)
        if question == cases[1]["input"]:
            raise RuntimeError("private-test-value")
        return "You have £1.0m."

    monkeypatch.setattr(runner, "agent_loop", fake_agent)
    runner.run_cases(settings, cases, destination, run_id="test-run")
    records = runner.load_cases(destination)

    assert questions == [case["input"] for case in cases]
    assert [record["status"] for record in records] == [
        "completed", "error",
    ]
    assert records[1]["error_type"] == "RuntimeError"
    assert {record["run_id"] for record in records} == {"test-run"}
    assert [record["trace_id"] for record in records] == [
        "trace-bank", "trace-chip",
    ]
    assert "private-test-value" not in destination.read_text()


def test_existing_batch_file_prevents_agent_calls(cases, tmp_path):
    destination = tmp_path / "existing.jsonl"
    destination.write_text("original\n", encoding="utf-8")
    settings = Settings(entry_id=None, data_dir=tmp_path)

    with pytest.raises(FileExistsError):
        runner.run_cases(settings, cases, destination)

    runner.agent_loop.assert_not_called()
    assert destination.read_text() == "original\n"


def test_scoring_matches_ids_and_keeps_source_records(
    cases, saved_results,
):
    original = deepcopy(saved_results)
    scored = runner.score_results(cases, list(reversed(saved_results)))
    by_id = {record["case_id"]: record for record in scored}

    assert by_id["bank"]["scores"] == {
        "tool_selection": {"score": 1, "missing_tools": []},
        "argument_validity": {"score": 1, "issues": []},
    }
    assert by_id["chip"]["scores"]["tool_selection"]["score"] == 1
    assert by_id["chip"]["scores"]["argument_validity"]["score"] == 0
    assert saved_results == original
    assert "scores" not in saved_results[0]


@pytest.mark.parametrize("problem", [
    "duplicate-case", "duplicate-result", "unknown-case",
    "wrong-snapshot", "missing-result", "empty-results",
])
def test_scoring_rejects_inconsistent_records(
    cases, saved_results, problem,
):
    if problem == "duplicate-case":
        cases.append(deepcopy(cases[0]))
    elif problem == "duplicate-result":
        saved_results.append(deepcopy(saved_results[0]))
    elif problem == "unknown-case":
        saved_results[0]["case_id"] = "unknown"
    elif problem == "wrong-snapshot":
        saved_results[0]["snapshot_id"] = "another-snapshot"
    elif problem == "missing-result":
        saved_results.pop()
    elif problem == "empty-results":
        saved_results.clear()

    with pytest.raises(ValueError):
        runner.score_results(cases, saved_results)


def test_merge_keeps_all_scores_metadata_and_source_records(
    scored_results, reviews,
):
    scored_results[0]["trace_id"] = "synthetic-trace"
    scored_results[0]["error_type"] = "SyntheticError"
    original_results = deepcopy(scored_results)
    original_reviews = deepcopy(reviews)

    combined = runner.merge_reviews(scored_results, reviews, "test-run")
    review_by_id = {review["case_id"]: review for review in reviews}

    assert len(combined) == 2
    for source, result in zip(scored_results, combined):
        review = review_by_id[result["case_id"]]
        assert result["run_id"] == "test-run"
        assert set(result["scores"]) == {
            "tool_selection", "argument_validity", "fact_recall",
            "groundedness", "task_success",
        }
        for name, value in source.items():
            if name != "scores":
                assert result[name] == value
        assert result["scores"]["tool_selection"] == (
            source["scores"]["tool_selection"]
        )
        assert result["scores"]["task_success"] == (
            review["scores"]["task_success"]
        )
        assert result["primary_cause"] == review["primary_cause"]
        assert result["note"] == review["note"]

    assert scored_results == original_results
    assert reviews == original_reviews
    assert json.loads(json.dumps(combined)) == combined


@pytest.mark.parametrize("problem", [
    "duplicate-result", "duplicate-review", "missing-review",
    "unknown-review", "missing-result", "wrong-review-run",
    "wrong-result-run", "overlap",
])
def test_merge_rejects_inconsistent_records(
    scored_results, reviews, problem,
):
    if problem == "duplicate-result":
        scored_results.append(deepcopy(scored_results[0]))
    elif problem == "duplicate-review":
        reviews.append(deepcopy(reviews[0]))
    elif problem == "missing-review":
        reviews.pop()
    elif problem == "unknown-review":
        reviews[0]["case_id"] = "unknown"
    elif problem == "missing-result":
        scored_results.pop()
    elif problem == "wrong-review-run":
        reviews[0]["run_id"] = "wrong-run"
    elif problem == "wrong-result-run":
        scored_results[0]["run_id"] = "wrong-run"
    elif problem == "overlap":
        reviews[0]["scores"]["tool_selection"] = {"score": 0}

    with pytest.raises(ValueError):
        runner.merge_reviews(scored_results, reviews, "test-run")


def test_merge_uses_requested_run_id(scored_results, reviews):
    for review in reviews:
        review["run_id"] = "another-run"

    combined = runner.merge_reviews(
        scored_results, reviews, "another-run",
    )

    assert {record["run_id"] for record in combined} == {"another-run"}


def test_merge_accepts_matching_recorded_run_id(scored_results, reviews):
    for result in scored_results:
        result["run_id"] = "test-run"

    combined = runner.merge_reviews(scored_results, reviews, "test-run")

    assert len(combined) == 2


def test_save_results_streams_unicode_records(tmp_path):
    destination = tmp_path / "nested" / "results.jsonl"
    records = [{"case_id": "one", "answer": "Groß"}, {"case_id": "two"}]

    def produce_records():
        yield records[0]
        assert runner.load_cases(destination) == [records[0]]
        yield records[1]

    runner.save_results(produce_records(), destination)

    assert runner.load_cases(destination) == records
    assert "Groß" in destination.read_text(encoding="utf-8")


def test_save_results_does_not_overwrite_or_consume_generator(tmp_path):
    destination = tmp_path / "existing.jsonl"
    destination.write_text("original\n", encoding="utf-8")

    def forbidden_records():
        raise AssertionError("Records must not be consumed")
        yield {}

    with pytest.raises(FileExistsError):
        runner.save_results(forbidden_records(), destination)

    assert destination.read_text() == "original\n"
