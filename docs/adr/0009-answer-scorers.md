# ADR-0009: Answer scorers

- Status: Accepted
- Date: 2026-11-21
- Source: code comments, moved here by the comment clean-up

## Context

The automatic scorers check that each number in an answer comes from tool output. Models round, scale and format numbers in several ways.

## Decision

A number is supported if a tool value explains it under one of the rules below. A check that does not apply to a case scores `None`, and summaries leave it out. Only the listed safety flags are scored automatically; the other `must_*` flags stay in manual review. The runner saves each case before it starts the next one.

### Where this applies

Each entry gives the file, the symbol and the line of code that the reason was attached to. The reason under it is in its original words.

- `src/fpl/evals/runner.py` › `run_cases` › `records = (`
  - The generator starts only after save_results opens the new file.
- `src/fpl/evals/runner.py` › `summarise_results` › `if score is None:`
  - An answer check scores None when it does not apply to the case.
- `src/fpl/evals/scorers.py` › `is_supported` › `if decimals == 0 and source == target:`
  - A whole number as is cannot explain "10.0" (GW10).
- `src/fpl/evals/scorers.py` › `is_supported` › `if round(source / 10, decimals) == target:`
  - Prices are stored in tenths: 62 means 6.2.
- `src/fpl/evals/scorers.py` › `is_supported` › `if round(source, decimals) == target:`
  - Rounded: 3.7819 can appear as 3.78 or 3.8.
- `src/fpl/evals/scorers.py` › `is_supported` › `if round(source * 100, decimals) == target:`
  - A share as a percentage: 0.41 can appear as 41.
- `src/fpl/evals/scorers.py` › `score_numbers` › `if answer is None:`
  - score: None if it does not apply to the specific case i.e. no numbers to score
- `src/fpl/evals/scorers.py` › `BENCH_LABEL = re.compile(`
  - A bench label starts its line, as in "**Ordered bench:**" or "### Bench".
- `src/fpl/evals/scorers.py` › `SAFETY_FLAGS = [`
  - Other must_* flags, such as must_not_guess_element_id, stay in manual review.

## Consequences

- Each new matching rule can hide a wrong number. Add one only with a test case.
- A `None` score is not a pass. Report it separately.
