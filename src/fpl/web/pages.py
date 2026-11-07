"""Data each Release 1 page receives: the routes fill these and the templates render them."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fpl.evals.export import Case, Run


@dataclass
class Ratio:
    passed: int
    total: int


@dataclass
class Shell:
    active: Literal["evals", "history"]
    snapshot_gw: int
    snapshot_created_at: datetime
    pilot_model: str
    pilot_temperature: float


@dataclass
class RunRow:
    run_id: str
    dataset: str
    case_count: int
    completed: Ratio
    tool_selection: Ratio
    argument_validity: Ratio
    # Cases that passed every numbers, teams and safety check that applies; None before Step 19.
    answer_checks: Ratio | None
    task_success: Ratio | None
    model: str
    temperature: float | None
    median_latency_s: float | None
    cost_per_case_usd: float | None
    commit: str
    created_at: datetime


@dataclass
class RunGroup:
    group: str
    # run_id holds the group name; ratios are summed over the runs.
    total: RunRow
    runs: list[RunRow]


@dataclass
class FailedCheck:
    case_id: str
    checks: list[Literal["tool", "arguments", "numbers", "teams", "safety"]]
    detail: str


@dataclass
class EvalsPage:
    shell: Shell
    latest: RunRow
    groups: list[RunGroup]
    failed_checks: list[FailedCheck]


@dataclass
class HistoryRow:
    asked_at: datetime
    run_id: str
    case_id: str
    question: str
    tools: list[str]
    status: Literal["completed", "error"]
    trace_id: str


@dataclass
class HistoryPage:
    shell: Shell
    q: str
    run: str
    status: str
    tool: str
    page: int
    page_size: int
    total: int
    run_options: list[str]
    tool_options: list[str]
    rows: list[HistoryRow]

    @property
    def page_count(self) -> int:
        return max(1, -(-self.total // self.page_size))


@dataclass
class AnswerPage:
    shell: Shell
    run: Run
    case: Case
