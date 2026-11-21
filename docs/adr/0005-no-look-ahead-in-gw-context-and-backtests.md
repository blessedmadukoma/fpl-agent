# ADR-0005: No look-ahead in the GW context and the backtests

- Status: Accepted
- Date: 2026-11-21
- Source: code comments, moved here by the comment clean-up

## Context

Backtests replay past gameweeks. Data from after a deadline would make the results look better than they are.

## Decision

`GwContext` holds the player state at the deadline, the `player_gw` rows of the season with `gw < self.gw`, and fixture results only for `gw < self.gw`. The replay inner-joins projections and outcomes, so a player with no fixture in a GW has no outcome row and is left out.

### Where this applies

Each entry gives the file, the symbol and the line of code that the reason was attached to. The reason under it is in its original words.

- `src/fpl/backtest/replay.py` › `replay` › `frame = projected.merge(`
  - Inner join: a player with no fixture that GW has no outcome row and is left out.
- `src/fpl/context.py` › `GwContext` › `state: pd.DataFrame`
  - one row per player: status, flags, price, ep_next, ... at the deadline
- `src/fpl/context.py` › `GwContext` › `history: pd.DataFrame`
  - player_gw rows of this season with gw < self.gw
- `src/fpl/context.py` › `GwContext` › `fixtures: pd.DataFrame`
  - every fixture of the season (results only used for gw < self.gw)

## Consequences

- A new field in `GwContext` must use the same cut-off.
- tests/test_agent_tools.py adds a future row and another season to the fixture to catch a missing filter (ADR-0011).
