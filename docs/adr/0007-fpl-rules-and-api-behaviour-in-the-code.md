# ADR-0007: FPL rules and API behaviour in the code

- Status: Accepted
- Date: 2026-11-21
- Source: code comments, moved here by the comment clean-up

## Context

Some code follows FPL game rules or API behaviour that the API does not document, such as Free Hit reversion, purchase prices and blank gameweeks.

## Decision

The code follows the rules listed below.

### Where this applies

Each entry gives the file, the symbol and the line of code that the reason was attached to. The reason under it is in its original words.

- `src/fpl/fplapi.py` › `FplClient` › `def bootstrap(self) -> dict:`
  - Named helpers to prevent callers from building URLS by hand
- `src/fpl/ingest/current.py` › `LIVE_STATS = [`
  - Per-player stats we keep from event/{gw}/live. Numeric strings (xG) are cast to float.
- `src/fpl/ingest/current.py` › `player_gw_frame` › `if not element["explain"]:`
  - the player's team had no fixture (blank GW)
- `src/fpl/ingest/history.py` › `index` › `"/")`
  - cache/Y/M/D/HHMM
- `src/fpl/ingest/odds.py` › `CLUB_CODES = {`
  - football-data club name -> FPL short name (stable across seasons)
- `src/fpl/team_state.py` › `reconstruct` › `base_gw = last_gw - 1 if chips_by_gw.get(last_gw) == "freehit" else...`
  - After a Free Hit, the picks for that GW are the Free Hit squad; the real squad reverted.
- `src/fpl/team_state.py` › `free_transfers` › `free = 1`
  - the first GW after I join
- `src/fpl/team_state.py` › `_purchase_prices` › `elif started_event == 1:`
  - prices do not change before the GW1 deadline
- `src/fpl/team_state.py` › `_purchase_prices` › `else:`
  - joined later: the price in the round you joined
- `tests/test_prices_and_transfers.py` › `test_wildcard_week_keeps_saved_transfers_without_the_plus_one` › `assert free_transfers(`
  - GW2 +0 -> 2 for GW3; wildcard in GW3 keeps 2 for GW4

## Consequences

- When FPL changes a rule for a new season, check each place below.
- Add a rule here when new code depends on undocumented FPL behaviour.
