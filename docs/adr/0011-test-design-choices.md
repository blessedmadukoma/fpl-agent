# ADR-0011: Test design choices

- Status: Accepted
- Date: 2026-11-21
- Source: code comments, moved here by the comment clean-up

## Context

Some tests use fixture rows, orders or real models on purpose. Without the reason, a later edit could remove what the test depends on.

## Decision

Keep the test properties listed below.

### Where this applies

Each entry gives the file, the symbol and the line of code that the reason was attached to. The reason under it is in its original words.

- `tests/test_agent_loop.py` › `runtime` › `monkeypatch.setattr(loop, "message_client", lambda message: [`
  - Check file loading separately so a prompt bug does not mask loop behaviour.
- `tests/test_agent_tools.py` › `frozen_team` › `con.execute(`
  - Distracting rows catch queries that omit the season or GW filter.
- `tests/test_agent_tools.py` › `frozen_team` › `con.execute(`
  - A future row and another season must not enter historical answers.
- `tests/test_agent_tools.py` › `test_missing_player` › `with connect_path(frozen_team.database_path, read_only=True) as con:`
  - Exercise the tool directly; the deliberate change invalidates snapshot hashes.
- `tests/test_eval_runner.py` › `reviews` › `return [`
  - Review order differs from result order to check the ID matching.
- `tests/test_minutes.py` › `test_gw9_training_skips_missing_gw8_state` › `model = minutes_model.train(training_db, gws)`
  - Use real features and regressions, not a mocked training implementation.
- `tests/test_minutes.py` › `test_gw9_training_skips_missing_gw8_state` › `assert 8 in ctx.history.gw.to_list()`
  - Skipping a training example must not discard actual GW8 history.
- `tests/test_prices_and_transfers.py` › `test_the_example_team` › `assert free_transfers(_weeks(0, 0, 0, 2, 2), {},`
  - Entry 1234567 in 2026/27: no transfers in GW2-3, two in GW4, two in GW5 -> 1 for GW6
- `tests/test_scoring.py` › `RULES = Rules(`
  - The 2026/27 coefficients, as returned in game_config.scoring (only the keys score() uses).

## Consequences

- When you change one of these fixtures, keep the property that the entry names.
