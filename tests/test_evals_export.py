"""Evaluation export checks with one synthetic run."""

import json

import pytest

from fpl.evals.export import RunExport, export_runs


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


@pytest.fixture
def evals_dir(tmp_path):
    evals = tmp_path / "evals"
    write_jsonl(evals / "runs" / "demo-r1-manifest.jsonl", [{
        "snapshot_id": "frozen", "season": "2026-27", "gw": "9",
        "code_commit": "314e3c9" + "0" * 33, "code_dirty": "false", "model": "glm-5.3:cloud",
        "dataset_file": "cases.jsonl", "dataset_hash": "abc", "case_count": 1,
        "creation_time": "2026-11-04T23:22:06+00:00", "prompt_file": "system-v3.md",
    }])
    write_jsonl(evals / "runs" / "demo-r1-scored.jsonl", [{
        "case_id": "bank", "run_id": "demo-r1", "trace_id": "t1", "snapshot_id": "frozen",
        "input": "What is the bank of my team in the Example League?",
        "answer": "**EXAMPLE FC** has £1.1m in the bank.",
        "status": "completed",
        "tool_calls": [{
            "tool_call_id": "call_1", "name": "get_my_team", "raw_arguments": "{}", "arguments": {},
            "status": "completed", "result": {"team_name": "Example FC", "bank_in_tenths": 11},
        }],
        "scores": {
            "tool_selection": {"score": 1, "missing_tools": []},
            "numbers_validity": {"score": 0, "unsupported": ["£2.0m"]},
            "teams_validity": {"score": None, "missing": []},
        },
    }])
    write_jsonl(evals / "runs" / "post-gw6-01-reviews-v2.jsonl", [])
    write_jsonl(evals / "reviews" / "step19d-glm-5-3-cloud-task-success.jsonl", [{
        "case_id": "bank", "run_id": "demo-r1",
        "scores": {"task_success": {"score": 1, "reason": "correct"}}, "note": "Correct.",
    }])
    (evals / "langfuse").mkdir()
    (evals / "langfuse" / "demo-r1.json").write_text(json.dumps({"run_id": "demo-r1", "cases": [{
        "case_id": "bank", "trace_id": "t1", "found": True, "started_at": "2026-11-04T23:22:07+00:00",
        "latency_s": 3.8, "model_calls": 2, "input_tokens": 4474, "output_tokens": 126,
    }]}), encoding="utf-8")
    return evals


def test_export_redacts_names_and_keeps_the_figures(evals_dir, tmp_path):
    out = tmp_path / "out"

    assert export_runs(evals_dir, out, "Example FC", "Example League", 1234567) == 1

    text = (out / "demo-r1.json").read_text(encoding="utf-8")
    assert "example fc" not in text.lower()
    assert "example league" not in text.lower()
    assert "tool_call_id" not in text and "raw_arguments" not in text

    export = RunExport.model_validate_json(text)
    assert export.run.group == "demo"
    assert export.run.commit == "477f1ba"
    assert export.run.target_gw == 9
    assert export.run.commit_dirty is False
    assert export.run.temperature is None
    assert export.run.price.input == 1.40
    case = export.cases[0]
    assert case.question == "What is the bank of my team in the [league name]?"
    assert case.answer == "**[team name]** has £1.1m in the bank."
    assert case.tool_calls[0].result["team_name"] == "[team name]"
    assert case.checks["numbers_validity"].detail == ["£2.0m"]
    assert case.review.task_success == 1
    assert case.latency_s == 3.8


def test_export_stops_on_the_entry_id(evals_dir, tmp_path):
    scored = evals_dir / "runs" / "demo-r1-scored.jsonl"
    scored.write_text(scored.read_text(encoding="utf-8").replace("in the bank.", "in the bank (entry 7654321)."),
                      encoding="utf-8")

    with pytest.raises(SystemExit, match="7654321"):
        export_runs(evals_dir, tmp_path / "out", "Example FC", "Example League", 7654321)
