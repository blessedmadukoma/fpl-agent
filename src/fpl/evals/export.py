"""Write each saved evaluation run as one redacted JSON file that the web pages read."""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from fpl.config import PROJECT_ROOT
from fpl.evals.runner import load_cases

EXPORT_DIR = PROJECT_ROOT / "exports" / "evals"

# Hand reviews, relative to data/evals.
REVIEW_FILES = (
    "runs/post-gw6-01-reviews-v2.jsonl",
    "reviews/step19d-glm-5-3-cloud-task-success.jsonl",
)

# The history rewrite replaced these commits after the runs recorded them.
NEW_COMMITS = {
    "e28400a": "de44110",
    "89e4d96": "800771b",
    "314e3c9": "477f1ba",
    "7f27aba": "6b59f12",
    "a331f68": "c65b961",
}

DETAIL_KEYS = {
    "tool_selection": "missing_tools",
    "argument_validity": "issues",
    "numbers_validity": "unsupported",
    "teams_validity": "missing",
    "safety_validity": "failed",
}

Score = Literal[0, 1]


class Price(BaseModel):
    """USD per million tokens."""

    input: float
    output: float
    read_on: date


# From https://ollama.com/pricing. gemma4:12b runs locally and has no price.
PRICES = {
    model: Price(input=input_price, output=output_price, read_on=date(2026, 11, 5))
    for model, input_price, output_price in [
        ("deepseek-v4.1-flash:cloud", 0.30, 1.20),
        ("gemma4:cloud", 0.14, 0.40),
        ("glm-5.3:cloud", 1.40, 4.40),
        ("gpt-oss:120b-cloud", 0.15, 0.60),
        ("kimi-k3:cloud", 3.00, 15.00),
        ("minimax-m3.1-flash:cloud", 0.15, 0.60),
    ]
}


class Run(BaseModel):
    run_id: str
    group: str
    created_at: datetime
    model: str
    temperature: float | None
    dataset_file: str
    dataset_hash: str
    snapshot_id: str
    season: str
    target_gw: int
    prompt_file: str
    commit: str
    commit_dirty: bool
    price: Price | None


class Check(BaseModel):
    score: Score | None
    detail: list[str]


class Review(BaseModel):
    task_success: Score
    fact_recall: Score | None = None
    groundedness: Score | None = None
    note: str


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]
    status: Literal["completed", "rejected", "error"]
    error_type: str | None = None
    result: Any = None


class Case(BaseModel):
    case_id: str
    question: str
    answer: str | None
    status: Literal["completed", "error"]
    error_type: str | None
    trace_id: str
    # None when Langfuse has no trace for the case.
    started_at: datetime | None
    latency_s: float | None
    model_calls: int | None
    input_tokens: int | None
    output_tokens: int | None
    checks: dict[str, Check]
    review: Review | None
    tool_calls: list[ToolCall]


class RunExport(BaseModel):
    run: Run
    cases: list[Case]


def load_reviews(evals_dir: Path) -> dict[tuple[str, str], Review]:
    reviews = {}
    for name in REVIEW_FILES:
        for record in load_cases(evals_dir / name):
            scores = {check: value["score"] for check, value in record["scores"].items()}
            reviews[record["run_id"], record["case_id"]] = Review(**scores, note=record["note"])
    return reviews


def export_run(evals_dir: Path, run_id: str, reviews: dict[tuple[str, str], Review]) -> RunExport:
    runs_dir = evals_dir / "runs"
    manifest = load_cases(runs_dir / f"{run_id}-manifest.jsonl")[0]
    scored_path = runs_dir / f"{run_id}-rescored.jsonl"
    if not scored_path.exists():
        scored_path = runs_dir / f"{run_id}-scored.jsonl"
    langfuse = json.loads((evals_dir / "langfuse" / f"{run_id}.json").read_text(encoding="utf-8"))
    traces = {trace["case_id"]: trace for trace in langfuse["cases"]}

    commit = manifest["code_commit"][:7]
    run = Run(
        run_id=run_id,
        group=re.sub(r"-r\d+$", "", run_id),
        created_at=manifest["creation_time"],
        model=manifest["model"],
        temperature=manifest.get("temperature"),
        dataset_file=manifest["dataset_file"],
        dataset_hash=manifest["dataset_hash"],
        snapshot_id=manifest["snapshot_id"],
        season=manifest["season"],
        target_gw=manifest["gw"],
        prompt_file=manifest["prompt_file"],
        commit=NEW_COMMITS.get(commit, commit),
        commit_dirty=manifest["code_dirty"],
        price=PRICES.get(manifest["model"]),
    )

    cases = []
    for record in load_cases(scored_path):
        trace = traces[record["case_id"]]
        cases.append(Case(
            case_id=record["case_id"],
            question=record["input"],
            answer=record["answer"],
            status=record["status"],
            error_type=record.get("error_type"),
            trace_id=record["trace_id"],
            started_at=trace["started_at"],
            latency_s=trace["latency_s"],
            model_calls=trace["model_calls"],
            input_tokens=trace["input_tokens"],
            output_tokens=trace["output_tokens"],
            checks={
                name: Check(score=value["score"], detail=value[DETAIL_KEYS[name]])
                for name, value in record["scores"].items()
            },
            review=reviews.get((run_id, record["case_id"])),
            tool_calls=[ToolCall.model_validate(call) for call in record["tool_calls"]],
        ))
    return RunExport(run=run, cases=cases)


def export_runs(evals_dir: Path, out_dir: Path, team_name: str, league_name: str, entry_id: int) -> int:
    """Write every run that has a manifest; return the number of runs written."""
    reviews = load_reviews(evals_dir)
    run_ids = sorted(
        path.name.removesuffix("-manifest.jsonl")
        for path in (evals_dir / "runs").glob("*-manifest.jsonl")
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    for run_id in run_ids:
        text = export_run(evals_dir, run_id, reviews).model_dump_json(indent=1)
        text = re.sub(re.escape(team_name), "[team name]", text, flags=re.IGNORECASE)
        text = re.sub(re.escape(league_name), "[league name]", text, flags=re.IGNORECASE)
        for private in (str(entry_id), "/Users/"):
            if private in text:
                raise SystemExit(f"Stopped: {run_id} contains private text {private!r}.")
        (out_dir / f"{run_id}.json").write_text(text + "\n", encoding="utf-8")
    return len(run_ids)
