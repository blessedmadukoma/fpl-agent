# ADR-0006: Projection constants and their sources

- Status: Accepted
- Date: 2026-11-21
- Source: code comments, moved here by the comment clean-up

## Context

The projection models use tuned constants. Their values come from the 2025/26 replay and from docs/01-reference.md §H.2 and §I.

## Decision

Keep the values below. Each entry gives the source of the value.

### Where this applies

Each entry gives the file, the symbol and the line of code that the reason was attached to. The reason under it is in its original words.

- `src/fpl/projections/baseline.py` › `SHRINK_APPEARANCES = 4`
  - Prior weight, in appearances. Tuned on the 2025/26 replay: k = 4 gives a bias near zero and halves the over-projection of the top 15 players per GW (01-reference.md §I).
- `src/fpl/projections/minutes.py` › `news_kind` › `if back < deadline - pd.Timedelta(days=180):`
  - e.g. "Expected back 3 Jan" said in December
- `src/fpl/projections/points.py` › `PRIOR_90S = 6.0`
  - shrinkage strength k, in 90-minute matches (H.2)
- `src/fpl/projections/points.py` › `DEFCON_DISPERSION = 16.0`
  - negative-binomial φ, estimated per player on 2025/26 (close to Poisson)
- `src/fpl/projections/points.py` › `PointsModel` › `previous: pd.DataFrame`
  - last season's totals per player code (may be empty)
- `src/fpl/projections/teams.py` › `DECAY_PER_DAY = 0.005`
  - weight halves about every 140 days

## Consequences

- Retune a constant only with a new replay, and update this ADR with the new numbers.
