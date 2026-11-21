# ADR-0008: Public evaluation exports

- Status: Accepted
- Date: 2026-11-21
- Source: code comments, moved here by the comment clean-up

## Context

The files in exports/evals are public and feed the web pages. They are built from private runs, reviews and Langfuse traces.

## Decision

The exports leave out the team and league names. They map commit IDs that a history rewrite replaced. Model prices come from https://ollama.com/pricing, read on 5 November 2026; `gemma4:12b` runs locally and has no price. A case with no Langfuse trace has `None` timing fields. `answer_checks` is `None` for runs before Step 19.

### Where this applies

Each entry gives the file, the symbol and the line of code that the reason was attached to. The reason under it is in its original words.

- `src/fpl/config.py` › `Settings` › `team_name: str = ""`
  - Removed from the evaluation exports, which are public.
- `src/fpl/evals/export.py` › `NEW_COMMITS = {`
  - The history rewrite replaced these commits after the runs recorded them.
- `src/fpl/evals/export.py` › `PRICES = {`
  - From https://ollama.com/pricing. gemma4:12b runs locally and has no price.
- `src/fpl/evals/export.py` › `Case` › `started_at: datetime | None`
  - None when Langfuse has no trace for the case.
- `src/fpl/web/pages.py` › `RunRow` › `answer_checks: Ratio | None`
  - Cases that passed every numbers, teams and safety check that applies; None before Step 19.

## Consequences

- A new private field in `Settings` must be checked against the export before release.
- When prices change, update `PRICES` and its `read_on` date together.
