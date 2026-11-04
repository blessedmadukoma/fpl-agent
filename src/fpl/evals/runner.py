"""Run cases and score, review and save evaluation records."""

import json
from collections.abc import Iterable
from pathlib import Path

from fpl.agent.loop import agent_loop
from fpl.config import Settings
from fpl.evals.scorers import (
    score_arguments,
    score_numbers,
    score_teams,
    score_tool_selection,
)


def load_cases(evals_json: Path) -> list[dict]:
    """Read JSONL records, ignoring blank lines."""
    with evals_json.open("r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    cases = []
    for line in lines:
        if not line.strip():
            continue
        case = json.loads(line)
        cases.append(case)
    return cases


def run_case(
    settings: Settings,
    case: dict,
    snapshot_root: Path = Path("data/evals/snapshots"),
    run_id: str | None = None,
) -> dict:
    """Record one agent answer or failure, including its tool calls."""
    snapshot_dir = snapshot_root / case["snapshot_id"]

    tool_calls = []
    trace_context = {"trace_id": None}

    try:
        answer = agent_loop(
            settings,
            case["input"],
            snapshot_dir,
            tool_calls=tool_calls,
            run_id=run_id,
            case_id=case["id"],
            trace_context=trace_context,
        )

        return {
            "case_id": case["id"],
            "run_id": run_id,
            "trace_id": trace_context["trace_id"],
            "snapshot_id": case["snapshot_id"],
            "input": case["input"],
            "answer": answer,
            "status": "completed",
            "tool_calls": tool_calls,
        }

    except Exception as error:
        return {
            "case_id": case["id"],
            "run_id": run_id,
            "trace_id": trace_context["trace_id"],
            "snapshot_id": case["snapshot_id"],
            "input": case["input"],
            "answer": None,
            "status": "error",
            "tool_calls": tool_calls,
            "error_type": type(error).__name__
        }


def run_cases(
    settings: Settings, cases: list[dict], output_path: Path,
    snapshot_root: Path = Path("data/evals/snapshots"),
    run_id: str | None = None,
) -> None:
    """Run each case and save it before starting the next case."""
    # The generator starts only after save_results opens the new file.
    records = (
        run_case(
            settings, case, snapshot_root=snapshot_root, run_id=run_id,
        )
        for case in cases
    )
    save_results(records, output_path)


def score_results(
    cases: list[dict], saved_results: list[dict],
) -> list[dict]:
    """Score a complete saved run using matching case and snapshot IDs."""
    case_by_id = {case["id"]: case for case in cases}
    if len(case_by_id) != len(cases):
        raise ValueError("Duplicate case IDs detected in cases")

    output = []

    seen_result_ids = set()

    for result in saved_results:
        case_id = result["case_id"]
        if case_id not in case_by_id:
            raise ValueError(f"Unknown case ID: {case_id}")
        if case_id in seen_result_ids:
            raise ValueError(f"Duplicate result case ID: {case_id}")
        seen_result_ids.add(case_id)

        case = case_by_id[case_id]
        if case["snapshot_id"] != result["snapshot_id"]:
            raise ValueError(
                f"Snapshot ID mismatch for case ID {case_id}: "
                f"case has {case['snapshot_id']!r}, "
                f"result has {result['snapshot_id']!r}"
            )

        result_copy = result.copy()
        result_copy["scores"] = {
            "tool_selection": score_tool_selection(case, result),
            "argument_validity": score_arguments(case, result),
            "numbers_validity": score_numbers(case, result),
            "teams_validity": score_teams(case, result),
        }
        output.append(result_copy)

    missing_case_ids = set(case_by_id) - seen_result_ids
    if missing_case_ids:
        raise ValueError(
            f"Missing results for case IDs: {sorted(missing_case_ids)}")

    return output


def save_results(
    scored_records: Iterable[dict], output_path: Path,
) -> None:
    """Write JSONL records to a new file without overwriting old results."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open(mode="x", encoding="utf-8") as output:
        for record in scored_records:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()


def merge_reviews(
    scored_results: list[dict],
    reviews: list[dict],
    expected_run_id: str,
) -> list[dict]:
    """Combine matching reviews and results without replacing scores."""
    result_by_id = {
        result["case_id"]: result
        for result in scored_results
    }
    if len(result_by_id) != len(scored_results):
        raise ValueError("Duplicate case IDs detected in scored results")

    review_by_id = {review["case_id"]: review for review in reviews}
    if len(review_by_id) != len(reviews):
        raise ValueError("Duplicate case IDs detected in reviews")

    missing_reviews = set(result_by_id) - set(review_by_id)
    unknown_reviews = set(review_by_id) - set(result_by_id)
    if missing_reviews or unknown_reviews:
        raise ValueError(
            "Case ID mismatch between scored results and reviews: "
            f"missing reviews for {sorted(missing_reviews)}, "
            f"unknown reviews for {sorted(unknown_reviews)}"
        )

    output = []

    for result in scored_results:
        case_id = result["case_id"]
        review = review_by_id[case_id]

        if "run_id" in result and result["run_id"] != expected_run_id:
            raise ValueError(
                f"Run ID mismatch in result for case ID {case_id}: "
                f"expected {expected_run_id!r}, "
                f"result has {result['run_id']!r}"
            )

        if review["run_id"] != expected_run_id:
            raise ValueError(
                f"Run ID mismatch in review for case ID {case_id}: "
                f"expected {expected_run_id!r}, "
                f"review has {review['run_id']!r}"
            )

        overlap = set(result["scores"]) & set(review["scores"])
        if overlap:
            raise ValueError(
                f"Overlapping score names for case ID {case_id}: "
                f"{sorted(overlap)}"
            )

        combined_scores = {
            **result["scores"],
            **review["scores"],
        }

        combined = result.copy()
        combined["scores"] = combined_scores
        combined["run_id"] = expected_run_id
        combined["primary_cause"] = review["primary_cause"]
        combined["note"] = review["note"]
        output.append(combined)

    return output


def summarise_results(reviewed_records):
    EXPECTED_METRICS = {
        "tool_selection", "argument_validity", "fact_recall",
        "groundedness", "task_success",
    }

    metric_totals: dict[str, int] = {}
    metric_passes: dict[str, int] = {}
    primary_cause_counts: dict[str, int] = {}

    for record in reviewed_records:
        if "scores" not in record or record["scores"] is None:
            raise ValueError(
                f"Missing scores for case ID {record.get('case_id')!r}"
            )
        scores = record["scores"]
        if set(scores) != EXPECTED_METRICS:
            raise ValueError("Each record needs all five scores")

        for name, value in scores.items():
            if value is None:
                raise ValueError(
                    f"Missing score {name!r} for case ID "
                    f"{record.get('case_id')!r}"
                )
            if "score" not in value:
                raise ValueError(
                    f"Missing 'score' in {name!r} for case ID "
                    f"{record.get('case_id')!r}"
                )
            score = value["score"]
            if score not in (0, 1):
                raise ValueError(
                    f"Score {name!r} for case ID "
                    f"{record.get('case_id')!r} out of range: {score!r}"
                )
            metric_totals[name] = metric_totals.get(name, 0) + 1
            if score == 1:
                metric_passes[name] = metric_passes.get(name, 0) + 1

        cause = record.get("primary_cause")
        if cause is not None:
            primary_cause_counts[cause] = (
                primary_cause_counts.get(cause, 0) + 1
            )

    metrics = {}
    for name, total in metric_totals.items():
        passed = metric_passes.get(name, 0)
        metrics[name] = {
            "passed": passed,
            "total": total,
            "pass_rate": (passed / total) if total else 0.0,
        }

    return {
        "case_count": len(reviewed_records),
        "metrics": metrics,
        "primary_cause_counts": primary_cause_counts,
    }
