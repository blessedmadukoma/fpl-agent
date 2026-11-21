# ADR-0003: Application settings and allow-lists bound the tool arguments

- Status: Accepted
- Date: 2026-11-21
- Source: code comments, moved here by the comment clean-up

## Context

The model fills the tool arguments. The application also sets some of them, such as the horizon. One tool reads a statistic column that the question names.

## Decision

An application setting overrides the model's value for the same argument. `get_historical_leaders` accepts only the statistics in a `Literal` allow-list and never builds SQL from model text.

### Where this applies

Each entry gives the file, the symbol and the line of code that the reason was attached to. The reason under it is in its original words.

- `src/fpl/agent/loop.py` › `agent_loop` › `arguments = {**arguments, "horizon": horizon}`
  - Explicit application settings outrank model guesses.
- `src/fpl/agent/tools.py` › `get_historical_leaders` › `conditions = "season = ? and gw = ?"`
  - statistic is a Literal allow-list, never arbitrary model-generated SQL.

## Consequences

- A new statistic must be added to the `Literal` type before the model can ask for it.
- Tests that check model arguments must expect the application value where one is set.
