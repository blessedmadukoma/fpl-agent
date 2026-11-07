import math
import statistics
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from fpl.evals.export import EXPORT_DIR, RunExport
from fpl.web.pages import (
    AnswerPage,
    EvalsPage,
    FailedCheck,
    HistoryPage,
    HistoryRow,
    Ratio,
    RunGroup,
    RunRow,
    Shell,
)
from fpl.web.templating import STATIC_DIR, templates

CSP = "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
HSTS = "max-age=31536000; includeSubDomains"
# FastAPI routes answer HEAD only when asked to; uptime monitors send it.
READ_METHODS = ["GET", "HEAD"]

EXPORTS = [RunExport.model_validate_json(path.read_text(
    encoding="utf-8")) for path in EXPORT_DIR.glob("*.json")]
CASES = {(export.run.run_id, case.case_id): (export.run, case)
         for export in EXPORTS for case in export.cases}
# The 4-case runs are smoke tests on a smaller dataset, so the pilot is the newest 20-case run.
LATEST = max((export for export in EXPORTS if len(export.cases)
             == 20), key=lambda export: export.run.created_at)
RUN_IDS = [export.run.run_id for export in sorted(
    EXPORTS, key=lambda export: export.run.created_at, reverse=True)]
TOOLS = sorted({call.name for _, case in CASES.values()
               for call in case.tool_calls})
PAGE_SIZE = 10
CHECK_LABELS = {"tool_selection": "tool", "argument_validity": "arguments", "numbers_validity": "numbers",
                "teams_validity": "teams", "safety_validity": "safety"}
ANSWER_CHECKS = ("numbers_validity", "teams_validity", "safety_validity")

# The default /docs page loads scripts from a CDN, which the CSP blocks.
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["Strict-Transport-Security"] = HSTS
    return response


def shell(active: str) -> Shell:
    run = LATEST.run
    # The snapshot ID starts with its creation time, for example 20261028_212650.
    created_at = datetime.strptime(run.snapshot_id[:15], "%Y%m%d_%H%M%S")
    return Shell(active=active, snapshot_gw=run.target_gw, snapshot_created_at=created_at,
                 pilot_model=run.model, pilot_temperature=run.temperature)


@app.api_route("/", methods=READ_METHODS)
def home():
    return RedirectResponse("/evals")


@app.api_route("/healthz", methods=READ_METHODS, response_class=PlainTextResponse)
def healthz():
    return "ok"


@app.api_route("/answers/{run_id}/{case_id}", methods=READ_METHODS)
def answer(request: Request, run_id: str, case_id: str):
    if (run_id, case_id) not in CASES:
        raise HTTPException(status_code=404)
    run, case = CASES[run_id, case_id]
    page = AnswerPage(shell=shell("history"), run=run, case=case)
    return templates.TemplateResponse(request, "answer.html", {"page": page})


@app.api_route("/history", methods=READ_METHODS)
def history(request: Request, q: str = "", run: str = "", status: str = "", tool: str = "", page: int = 1):
    rows = []
    for case_run, case in CASES.values():
        tools = list(dict.fromkeys(call.name for call in case.tool_calls))
        if (q.lower() in case.question.lower()
                and (not run or case_run.run_id == run)
                and (not status or case.status == status)
                and (not tool or tool in tools)):
            rows.append(HistoryRow(asked_at=case.started_at or case_run.created_at, run_id=case_run.run_id,
                                   case_id=case.case_id, question=case.question, tools=tools,
                                   status=case.status, trace_id=case.trace_id))
    rows.sort(key=lambda row: row.asked_at, reverse=True)

    page_count = max(1, math.ceil(len(rows) / PAGE_SIZE))
    page = min(max(page, 1), page_count)
    history_page = HistoryPage(
        shell=shell("history"), q=q, run=run, status=status, tool=tool, page=page, page_size=PAGE_SIZE,
        total=len(rows), run_options=RUN_IDS, tool_options=TOOLS,
        rows=rows[(page - 1) * PAGE_SIZE:page * PAGE_SIZE],
    )

    only_results = "HX-Request" in request.headers and "HX-History-Restore-Request" not in request.headers
    template = "history_results.html" if only_results else "history.html"
    response = templates.TemplateResponse(
        request, template, {"page": history_page})
    response.headers["Vary"] = "HX-Request"
    return response


def ratio(results: list[bool]) -> Ratio | None:
    return Ratio(passed=sum(results), total=len(results)) if results else None


def run_row(run_id: str, exports: list[RunExport]) -> RunRow:
    """One row of the runs table, counting every case in the given runs."""
    run = exports[0].run
    cases = [case for export in exports for case in export.cases]

    answer_checks = []
    for case in cases:
        scores = [check.score for name, check in case.checks.items()
                  if name in ANSWER_CHECKS and check.score is not None]
        if scores:
            answer_checks.append(all(score == 1 for score in scores))

    latencies = [
        case.latency_s for case in cases if case.latency_s is not None]
    costs = []
    for export in exports:
        price = export.run.price
        for case in export.cases:
            if price and case.input_tokens is not None:
                costs.append((case.input_tokens * price.input +
                             case.output_tokens * price.output) / 1_000_000)

    return RunRow(
        run_id=run_id,
        dataset=f"{run.dataset_file.removesuffix('.jsonl')} · {run.dataset_hash[:6]}",
        case_count=len(cases),
        completed=ratio([case.status == "completed" for case in cases]),
        tool_selection=ratio(
            [case.checks["tool_selection"].score == 1 for case in cases]),
        argument_validity=ratio(
            [case.checks["argument_validity"].score == 1 for case in cases]),
        answer_checks=ratio(answer_checks),
        task_success=ratio([case.review.task_success ==
                           1 for case in cases if case.review]),
        model=run.model,
        temperature=run.temperature,
        median_latency_s=statistics.median(latencies) if latencies else None,
        cost_per_case_usd=statistics.mean(costs) if costs else None,
        commit=run.commit,
        created_at=run.created_at,
    )


@app.api_route("/evals", methods=READ_METHODS)
def evals(request: Request):
    exports_by_group = {}
    for export in sorted(EXPORTS, key=lambda export: export.run.created_at):
        exports_by_group.setdefault(export.run.group, []).append(export)

    groups = []
    for group, exports in exports_by_group.items():
        runs = [run_row(export.run.run_id, [export]) for export in exports]
        total = runs[0] if len(runs) == 1 else run_row(group, exports)
        groups.append(RunGroup(group=group, total=total, runs=runs))
    groups.sort(key=lambda group: group.total.created_at, reverse=True)

    failed_checks = []
    for case in LATEST.cases:
        failed = [name for name, check in case.checks.items()
                  if check.score == 0]
        if failed:
            failed_checks.append(FailedCheck(
                case_id=case.case_id,
                checks=[CHECK_LABELS[name] for name in failed],
                detail="; ".join(
                    item for name in failed for item in case.checks[name].detail),
            ))

    page = EvalsPage(shell=shell("evals"), latest=run_row(LATEST.run.run_id, [LATEST]),
                     groups=groups, failed_checks=failed_checks)
    return templates.TemplateResponse(request, "evals.html", {"page": page})
