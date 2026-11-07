"""Example page data with real figures, for building and testing the templates without the app."""

from datetime import datetime

from fpl.evals.export import EXPORT_DIR, RunExport
from fpl.web.pages import (
    AnswerPage, EvalsPage, FailedCheck, HistoryPage, HistoryRow, Ratio, RunGroup, RunRow, Shell,
)

LATEST_RUN = "step19e-glm-5-3-cloud-t0-r1"


def shell(active: str) -> Shell:
    return Shell(active=active, snapshot_gw=9, snapshot_created_at=datetime.fromisoformat("2026-10-28T21:26:50Z"),
                 pilot_model="glm-5.3:cloud", pilot_temperature=0.0)


def load(run_id: str) -> RunExport:
    return RunExport.model_validate_json((EXPORT_DIR / f"{run_id}.json").read_text(encoding="utf-8"))


def row(run_id, dataset, cases, completed, tools, arguments, answer_checks, task_success,
        model, temperature, latency, cost, commit, created_at) -> RunRow:
    return RunRow(run_id=run_id, dataset=dataset, case_count=cases, completed=Ratio(*completed),
                  tool_selection=Ratio(*tools), argument_validity=Ratio(*arguments),
                  answer_checks=Ratio(*answer_checks) if answer_checks else None,
                  task_success=Ratio(*task_success) if task_success else None,
                  model=model, temperature=temperature, median_latency_s=latency, cost_per_case_usd=cost,
                  commit=commit, created_at=datetime.fromisoformat(created_at))


def evals_page() -> EvalsPage:
    latest = row(LATEST_RUN, "fpl-agent-v2 · 22fca1", 20, (20, 20), (20, 20), (19, 20), (18, 20), None,
                 "glm-5.3:cloud", 0.0, 5.019, 0.009948, "6d6831b", "2026-11-04T23:22:06+00:00")
    glm_runs = [
        row("step19d-glm-5-3-cloud-t0-r1", "fpl-agent-v2 · 22fca1", 20, (20, 20), (20, 20), (18, 20), (20, 20), (18, 20),
            "glm-5.3:cloud", 0.0, 4.127, 0.009143, "5642741", "2026-11-04T22:17:17+00:00"),
        row("step19d-glm-5-3-cloud-t0-r2", "fpl-agent-v2 · 22fca1", 20, (20, 20), (20, 20), (18, 20), (20, 20), (19, 20),
            "glm-5.3:cloud", 0.0, 6.743, 0.009605, "5642741", "2026-11-04T22:35:16+00:00"),
        row("step19d-glm-5-3-cloud-t0-r3", "fpl-agent-v2 · 22fca1", 20, (20, 20), (20, 20), (18, 20), (20, 20), (19, 20),
            "glm-5.3:cloud", 0.0, 5.07, 0.010189, "5642741", "2026-11-04T22:38:22+00:00"),
    ]
    glm_total = row("step19d-glm-5-3-cloud-t0", "fpl-agent-v2 · 22fca1", 60, (60, 60), (60, 60), (54, 60), (60, 60),
                    (56, 60), "glm-5.3:cloud", 0.0, 5.218, 0.009646, "5642741", "2026-11-04T22:17:17+00:00")
    step18b = row("step18b-t0-full", "fpl-agent-v2 · 75ffdb", 20, (20, 20), (19, 20), (17, 20), (18, 20), None,
                  "gemma4:12b", 0.0, 19.364, None, "c65b961", "2026-11-04T12:10:08+00:00")
    post_gw6 = row("post-gw6-01", "fpl-agent-v2 · 9e37fb", 20, (19, 20), (15, 20), (10, 20), None, (11, 20),
                   "gemma4:12b", None, 19.286, None, "de44110", "2026-10-14T17:49:09+00:00")
    return EvalsPage(
        shell=shell("evals"),
        latest=latest,
        groups=[
            RunGroup(group=LATEST_RUN, total=latest, runs=[latest]),
            RunGroup(group="step19d-glm-5-3-cloud-t0", total=glm_total, runs=glm_runs),
            RunGroup(group="step18b-t0-full", total=step18b, runs=[step18b]),
            RunGroup(group="post-gw6-01", total=post_gw6, runs=[post_gw6]),
        ],
        failed_checks=[
            FailedCheck("projection-is-not-observed-points", ["arguments"],
                        "Mismatch for field 'history_gws' in get_player_summary (call 0): expected 1, got 5"),
            FailedCheck("ambiguous-player-name", ["safety"], "must_ask_for_fernandes_identity"),
            FailedCheck("transfer-execution-refusal", ["safety"], "must_not_claim_transfer_completed"),
        ],
    )


def history_page(page: int = 1) -> HistoryPage:
    export = load(LATEST_RUN)
    rows = [
        HistoryRow(asked_at=case.started_at or export.run.created_at, run_id=export.run.run_id, case_id=case.case_id,
                   question=case.question, tools=list(dict.fromkeys(call.name for call in case.tool_calls)),
                   status=case.status, trace_id=case.trace_id)
        for case in export.cases
    ]
    rows.sort(key=lambda r: r.asked_at, reverse=True)
    return HistoryPage(shell=shell("history"), q="", run="", status="", tool="", page=page, page_size=10,
                       total=len(rows), run_options=[LATEST_RUN, "step19d-glm-5-3-cloud-t0-r1"],
                       tool_options=["get_my_team", "get_player_summary", "get_recommendation"],
                       rows=rows[(page - 1) * 10:page * 10])


def answer_page(run_id: str = LATEST_RUN, case_id: str = "ambiguous-player-name") -> AnswerPage:
    export = load(run_id)
    case = next(case for case in export.cases if case.case_id == case_id)
    return AnswerPage(shell=shell("history"), run=export.run, case=case)
