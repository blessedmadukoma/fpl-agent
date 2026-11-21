# ADR-0004: Optimiser objective and settings

- Status: Accepted
- Date: 2026-11-21
- Source: code comments, moved here by the comment clean-up

## Context

The transfer optimiser and the recommendation use weights and two plans whose meaning is not visible from the values. docs/01-reference.md §H.9 gives the free-transfer rule.

## Decision

The recommendation compares two plans. `plan` allows transfers in every GW. `hold` makes no transfer in the first GW (it rolls the transfer) and allows transfers later. The solver settings and plan fields have the meanings listed below.

### Where this applies

Each entry gives the file, the symbol and the line of code that the reason was attached to. The reason under it is in its original words.

- `src/fpl/agent/schemas.py` › `RecommendationResult` › `plan_objective: float`
  - transfers allowed in every GW
- `src/fpl/agent/schemas.py` › `RecommendationResult` › `hold_objective: float`
  - no transfer this GW (roll it), transfers allowed later
- `src/fpl/optimise/solver.py` › `SolverSettings` › `bench_weight: float = 0.15`
  - bench points only count through autosubs
- `src/fpl/optimise/solver.py` › `SolverSettings` › `decay: float = 0.9`
  - a point next week is worth less than a point this week
- `src/fpl/optimise/solver.py` › `SolverSettings` › `max_hits_per_gw: int = 0`
  - 0 = never take a hit; raise it with --max-hits
- `src/fpl/optimise/solver.py` › `SolverSettings` › `free_transfer_bonus: float = 0.01`
  - makes the reported free-transfer count exact (H.9)
- `src/fpl/optimise/solver.py` › `SolverSettings` › `hold_first_gw: bool = False`
  - no transfers in the first GW, later ones allowed ("roll")
- `src/fpl/optimise/solver.py` › `SolverSettings` › `candidates_per_position: int = 50`
  - plus your own players; keeps the problem small
- `src/fpl/optimise/solver.py` › `GwPlan` › `bench: list[int]`
  - in autosub order; the reserve goalkeeper is always first
- `src/fpl/optimise/solver.py` › `GwPlan` › `expected_points: float`
  - XI + captain, no bench
- `src/fpl/optimise/solver.py` › `optimise` › `if i == 0:`
  - Free transfers (H.9): hits for transfers beyond the free ones, then roll over
- `src/fpl/recommend.py` › `Recommendation` › `plan: Plan`
  - transfers allowed in every GW
- `src/fpl/recommend.py` › `Recommendation` › `hold: Plan`
  - no transfer this GW (roll it), transfers allowed later

## Consequences

- A change to a weight changes every recommendation and every backtest. Rerun the backtest and record the new reason here.
- The reported free-transfer count depends on `free_transfer_bonus`; do not set it to zero.
