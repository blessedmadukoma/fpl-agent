# FPL Agent 01 — Reference

Version 3, 26 September 2026. This file holds the facts, rules, formulas and target numbers. The
two build guides tell you what to do:

- **02-build-part1.md**, Steps 0–7: from an empty folder to a GW6 recommendation for your team.
- **03-build-part2.md**, Steps 8–13: better models, chips, the GW6 deadline runbook, and what comes
  after.

Read this file once. After that, use it for lookup. The build guides link to its sections, for
example "§D".

**Target: Gameweek 6 deadline, Saturday 10 October 2026, 10:00 UTC (12:00 in Kigali).**

- **Verified** means checked against the live FPL API or the cited source in the week of
  22 September 2026.
- **Replay** means a number produced by the code in the build guides, run on the 2025/26 season.
  You will reproduce every replay number yourself.

---

## Contents

|     | Section                                     |
| --- | ------------------------------------------- |
| A   | How the system works                        |
| B   | How to measure it                           |
| C   | Where the points are                        |
| D   | Scoring rules, chips and transfers, 2026/27 |
| E   | FPL API                                     |
| F   | Data sources                                |
| G   | Traps                                       |
| H   | Formulas, and the code that implements each |
| I   | Reference numbers (replay)                  |
| J   | GW6 calendar                                |
| K   | Deferred LLM and deployment work            |

---

## A. How the system works

```
FPL API ─┐                                   ┌─> projections (expected points per player per GW)
fplcache ├─> DuckDB (data/fpl.duckdb) ─> GwContext ─┤
vaastav  │                                   └─> your squad (rebuilt from public endpoints)
odds    ─┘                                             │
                                                      v
                              MILP solver ─> transfers, XI, captain, bench ─> terminal
```

**The one rule: a solver picks the team, never an LLM.** Squad selection is a constrained
optimisation problem, and a mixed-integer linear program (MILP) solves it exactly. The Part 3 LLM
may choose read-only tools, explain their deterministic output and extract news claims. It must
not calculate projections or select the squad.

**Leakage guard.** Every projection reads one `GwContext`: the players' state at the deadline,
plus results of earlier GWs only. A model that reads only a `GwContext` cannot see the future.
So the same code runs on a past GW (backtest) and on the next GW (live).

**Walking skeleton.** Part 1 ends with a complete pipeline on a simple projection (the shrunk
blend). Part 2 replaces the projection with a better model. The replacement happens only after
the model beats the skeleton in the backtest (§I).

---

## B. How to measure it

33 gameweeks remain. Weekly FPL scores vary by roughly 15–20 points, so this season cannot tell a
good system from a lucky one. Judge **projections** instead. You can measure them on thousands of
player-gameweeks from 2025/26.

**Use a loss that matches the solver.** The solver maximises expected points, so a projection must
estimate the mean.

- Squared error is minimised by the mean.
- Absolute error is minimised by the median \[1\].

FPL points are right-skewed, so MAE rewards projections that are biased low. Report these
instead:

- **RMSE**: accuracy of the mean.
- **Bias**: projected − realised.
- **ρ**: Spearman rank correlation within each GW, averaged over GWs. Ranking is what the solver
  uses.
- **Top-15 over-projection**: mean projected − mean realised for the 15 highest projections per GW.

**Fixed pools.** Measure on pools that you define before you look at any model:

- **Pool R:** regular starters, meaning 3 or more starts in the previous 4 GWs.
- **Pool O:** players owned by 1% or more at the deadline.

Do not score all players. That rewards you for predicting zero for players who never play.

**The optimiser's curse.** The solver picks the highest projections. Those are mostly the ones
whose error is positive, so the picks score less than projected, even when the projections are
unbiased overall \[2\]. You have three defences:

- shrinkage (H.2)
- no hits by default (H.6)
- a transfer threshold (H.8)

**Paired comparisons.** When you compare two versions of your own system on the same GWs, the
weekly difference varies much less than a raw score does. Use paired differences (Step 7 stores
both plans).

---

## C. Where the points are

2026/27 GW1–5: 1,538 appearances, 4,638 net points (verified from `event/{gw}/live/` `explain`).

| Component                      | Points | Share of net |
| ------------------------------ | -----: | -----------: |
| Appearance                     |  2,577 |        55.6% |
| Clean sheets                   |    786 |        16.9% |
| Goals                          |    655 |        14.1% |
| Assists                        |    390 |         8.4% |
| Defensive contribution         |    328 |         7.1% |
| Bonus                          |    316 |         6.8% |
| Saves                          |     63 |         1.4% |
| Penalties missed and own goals |    −20 |        −0.4% |
| Penalties saved                |     10 |         0.2% |
| Yellow and red cards           |   −204 |        −4.4% |
| Goals conceded                 |   −263 |        −5.7% |

**What separates players.** This table uses appearances of 60+ minutes. Each cell is the share of
the variance of a player's GW points that one component explains, computed as
cov(component, total) / var(total):

| Component              | All (n = 1,039) | DEF | MID | FWD |
| ---------------------- | --------------: | --: | --: | --: |
| Goals                  |             35% | 20% | 51% | 60% |
| Clean sheet            |             22% | 40% |  2% |  0% |
| Bonus                  |             18% | 14% | 21% | 26% |
| Assists                |             13% |  7% | 20% | 13% |
| Goals conceded         |              6% | 10% |  0% |  0% |
| Defensive contribution |              4% |  6% |  4% |  0% |
| Appearance             |              0% |  0% |  0% |  0% |

What this means:

- **Build the minutes model first.** Every other term scales with minutes, and a non-starter
  scores zero on all of them.
- **Once a player is expected to play, goals, clean sheets and bonus decide whether he is worth
  picking.**

DefCon hit rates, GW1–5 (verified):

| Position | Hit rate |
| -------- | -------- |
| DEF      | 20.1%    |
| MID      | 7.7%     |
| FWD      | 0.6%     |

---

## D. Scoring rules, chips and transfers, 2026/27

Verified against `game_config.scoring`:

| Action                 |     GKP |     DEF |     MID |     FWD |
| ---------------------- | ------: | ------: | ------: | ------: |
| Played 1–59 min        |       1 |       1 |       1 |       1 |
| Played 60+ min         |       2 |       2 |       2 |       2 |
| Goal                   |      10 |       6 |       5 |       4 |
| Assist                 |       3 |       3 |       3 |       3 |
| Clean sheet (60+ min)  |       4 |       4 |       1 |       0 |
| Every 2 goals conceded |      −1 |      −1 |       0 |       0 |
| Every 3 saves          |      +1 |       — |       — |       — |
| Penalty saved / missed | +5 / −2 |      −2 |      −2 |      −2 |
| Yellow / red card      | −1 / −3 | −1 / −3 | −1 / −3 | −1 / −3 |
| Own goal               |      −2 |      −2 |      −2 |      −2 |
| Defensive contribution |       0 |       2 |       2 |       2 |
| Bonus                  |     1–3 |     1–3 |     1–3 |     1–3 |

**Defensive contribution** (DefCon), capped at 2 points per match:

- DEF: 10 or more of clearances + blocks + interceptions + tackles (CBIT).
- MID and FWD: 12 or more of CBIT + ball recoveries.

**Rules the API does not give.** These live in `scoring.py`:

- the 60-minute line
- "per 2 goals conceded" and "per 3 saves"
- the DefCon thresholds

Steps 2 and 3 check the scoring function against every player of GW1–5 of 2026/27 and every
fixture of 2025/26. The result is **0 mismatches** (replay).

**BPS changes for 2026/27** \[3\]:

- A goalkeeper save gives 2 BPS, +1 if the shot was from inside the box, and +1 if it was a big
  chance.
- A penalty save gives +7 BPS (it was +8).
- Clearances, blocks and interceptions give 1 BPS per 3 actions (it was per 2).
- Being tackled no longer costs 1 BPS.

So fit bonus on 2026/27 matches only.

**Positions.** 11 players changed position for 2026/27 \[4\]. Score each season with that season's
positions.

**Chips** (verified in `bootstrap-static.chips` and the rules page \[5\]):

- There are two sets.
- Wildcard and Free Hit: GW2–19 and GW20–38.
- Bench Boost and Triple Captain: GW1–19 and GW20–38.
- You can play one chip per GW.
- **The first set expires at the GW19 deadline: 1 January 2027, 18:30 UTC.**
- A Free Hit cannot be played in consecutive GWs.

**Transfers:**

- You get 1 free transfer (FT) per GW. Unused FTs roll over, up to 5. An extra transfer costs 4
  points.
- A Wildcard or Free Hit keeps your saved FTs, and adds no +1 that week \[5\].
- A player's price changes by at most £0.3m per GW \[6\].
- Price changes happen daily at `price_change_deadlines`: 23:00 UTC now, 00:00 UTC after
  25 October.

---

## E. FPL API

Base: `https://fantasy.premierleague.com/api/`.

- It needs no key.
- Send a real `User-Agent`, and send one request at a time.

| Endpoint                       | Gives                                                              | Used in                               |
| ------------------------------ | ------------------------------------------------------------------ | ------------------------------------- |
| `bootstrap-static/`            | players, teams, events, prices, flags, chips, scoring coefficients | Step 1                                |
| `fixtures/`                    | every fixture, with results                                        | Step 1                                |
| `event/{gw}/live/`             | per-player stats per GW, and per-fixture `explain`                 | Steps 1, 2                            |
| `entry/{id}/`                  | your team name, first GW                                           | Step 5                                |
| `entry/{id}/history/`          | per-GW bank, value, transfers, chips played                        | Step 5                                |
| `entry/{id}/transfers/`        | every transfer, with prices                                        | Step 5                                |
| `entry/{id}/event/{gw}/picks/` | your 15 players for a past GW                                      | Step 5                                |
| `element-summary/{id}/`        | one player's match history                                         | Step 5 (only if you joined after GW1) |

**Rebuilding your squad** (`team_state.py`):

1. Take the picks from the last finished GW. **If that GW was a Free Hit**, take the picks from the
   GW before it: the Free Hit squad reverts.
2. Apply any later transfers, ignoring transfers made in a Free Hit week.
3. Purchase price:
   - for a player you transferred in, use `element_in_cost`;
   - for a player held since GW1, use `now_cost − cost_change_start`.
   - Transfers for the next GW may stay hidden until its deadline.
4. Selling price: purchase price + half of any rise, rounded down to £0.1m. You take the whole
   of any fall.
5. Free transfers: not in the API. Simulate them from `history` (H.9).

**Fields to know:**

- `now_cost` is in tenths of £1m (61 = £6.1m).
- `status` is a, d, i, s, u or n.
- `chance_of_playing_next_round` is null, 0, 25, 50, 75 or 100. It is a flag, not a probability
  (H.3).
- `news` holds text such as "Expected back 10 Oct".
- `ep_next` ≈ `form` × chance/100.
- `form` is a 30-day mean. At the GW6 deadline it covers GW4–5 only.
- `scout_risks` lists GWs in which a loan player may not face his parent club.
- `strength_attack_*` and `strength_defence_*` are 0 this season, so the team model is your own
  (H.4).

---

## F. Data sources

| Source                                             | What                                                   | Access             | Use                                                               | Caveat                                                                                                                                       |
| -------------------------------------------------- | ------------------------------------------------------ | ------------------ | ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| FPL API                                            | live state                                             | free               | everything live                                                   | changes in place and keeps no history; `fpl` saves every response in `data/raw/`                                                             |
| **fplcache** \[7\]                                 | raw `bootstrap-static`, about 4 times a day since 2021 | git, public domain | pre-deadline flags, `ep_next`, prices and ownership for backtests | for 2025/26 the last snapshot was 0.4–5.6 h before each deadline (median 4.3 h)                                                              |
| vaastav \[8\]                                      | results per player per fixture                         | git, MIT           | 2025/26 realised stats                                            | the `xP` column is scraped after the GW (lookahead): do not use it; the 2026-27 folder has GW1 only                                          |
| **football-data.co.uk** \[9\]                      | match odds (1X2, over/under 2.5)                       | free CSV           | team model, clean sheets                                          | Pinnacle columns are blank from January 2026, so the code uses the `Avg*` columns; weekend odds appear on Friday afternoon in `fixtures.csv` |
| FFScout team news \[10\], RotoWire line-ups \[11\] | predicted XIs                                          | free web pages     | manual check before the deadline (Step 12)                        | read their terms before you automate anything                                                                                                |
| FBref                                              | —                                                      | —                  | do not plan on it                                                 | advanced data removed in January 2026 \[12\]                                                                                                 |

---

## G. Traps

- **vaastav `xP` has lookahead.** Use fplcache `ep_next`.
- **Picks after a Free Hit are not your squad** (§E).
- **A flag is not a probability.** For a regular starter, a 75% flag meant a 48% start rate (H.3).
- **Never put expected minutes into a non-linear term.** Compute clean sheets, the goals-conceded
  floor, the saves floor and DefCon per minutes scenario (H.1).
- **MAE over all players is the wrong test** (§B).
- **Early-season numbers are noisy.** At GW6, PPG and form rest on 5 matches. With the raw blend
  and hits allowed, the solver recommends six transfers and five hits for a "gain" of +20 points
  (Step 6 shows this). Shrinkage, the no-hits default and the threshold fix it.
- **Promoted clubs** (Coventry, Hull, Ipswich) have no 2025/26 Premier League data. Their ratings
  come from this season's odds.
- **`scout_risks`**: the solver keeps such a player out of the XI in that GW, but does not force a
  sale.
- **Timezones**: all times in the database are UTC. DuckDB may print them in your local time.

---

## H. Formulas, and the code that implements each

**H.1 Expected points** (`projections/points.py`). For each player and fixture, with scenarios
60+ minutes (probability p60, about 85 min) and 1–59 minutes (p_short, about 22 min):

```
E[pts] = 2·p60 + 1·p_short
       + E[min]/90 · xG90 · attack_factor · goal_pts[pos]
       + E[min]/90 · xA90 · attack_factor · 3
       + p60 · P(CS) · cs_pts[pos]
       − Σ_s p_s · E[floor(GC_s/2)]        GC_s ~ Poisson(λ_against · m_s/90)     GKP, DEF
       + Σ_s p_s · E[floor(SV_s/3)]        SV_s ~ Poisson(saves90 · m_s/90)        GKP
       + Σ_s p_s · P(DC_s ≥ T[pos]) · 2    DC_s ~ NegBin(dc90 · m_s/90, φ = 16)    DEF, MID, FWD
       + E[bonus]                          H.7
       − E[min]/90 · yellow90
```

Example: a defender with p60 = 0.5 and P(CS) = 0.35 gets 0.5 × 0.35 × 4 = 0.7 clean-sheet points.
Without the p60 factor you would give him 1.4.

**H.2 Shrinkage** (`points.py: shrunk_rates`, `baseline.py: shrunk_blend`):

```
rate  = (k · prior + events) / (k + 90s played)          k = 6 (90s), prior = position mean
blend = (n · raw + k · prior) / (n + k)                  n = appearances, k = 4
```

For the current season, last season's minutes and events count at half weight.

**H.3 Minutes** (`projections/minutes.py`). Three logistic regressions, for P(start), P(60+) and
P(any minutes). The features are:

- started last GW
- starts and minutes in the last 4 GWs
- season start rate
- GWs so far
- flag category
- position
- `news` category, parsed with a regular expression ("Expected back 10 Oct" → back by the
  deadline)

Flags for regular starters, 2025/26 (replay):

| status, flag |     n | played | started |  60+ |
| ------------ | ----: | -----: | ------: | ---: |
| a, none      | 2,532 |   0.94 |    0.86 | 0.82 |
| d, 75        |   218 |   0.56 |    0.48 | 0.45 |
| d, 50        |    37 |   0.22 |    0.14 | 0.11 |
| d, 25        |    30 |   0.03 |    0.03 | 0.03 |
| i / s / n    |   251 |      0 |       0 |    0 |

**H.4 Team model** (`projections/goals.py`, `projections/teams.py`):

1. **Odds → λ.** Remove the bookmaker margin, then find the Poisson rates (λ_home, λ_away) that
   reproduce P(H, D, A) and P(over 2.5). Bookmaker odds are hard to beat for English football
   \[13\]\[14\].
2. **Ratings for fixtures that have no odds yet.** Fit a weighted ridge regression of log λ on
   team attack, team defence and home advantage. Fit it to the odds-implied λ of past fixtures,
   with weights that halve about every 140 days (Maher form \[15\]).
3. **Outputs.** `P(CS) = exp(−λ_against)`, and `attack_factor = λ_for / λ_average` for the team.

**H.5 Selling price** (`optimise/prices.py`):

```
sell = p + floor((now − p)/2)   if now > p
sell = now                      otherwise
```

**H.6 The solver** (`optimise/solver.py`). The variables, per player and GW, are: in squad, in XI,
captain, buy and sell. The constraints are:

- 15-man squad: 2 GKP, 5 DEF, 5 MID, 3 FWD
- XI of 11 with a legal formation
- at most 3 players per club
- bank ≥ 0, with selling prices
- free-transfer rollover (H.9)
- a hit limit (default 0)

The objective is: discounted EP of the XI + the captain, + 0.15 × EP of the bench, − 4 per hit.

**H.7 Bonus** (`points.py: fit_bonus`). A least-squares fit per position, on this season only:
bonus ≈ a + b·goals + c·assists + d·clean sheet + e·(60+). The fitted model is then applied to the
expected values.

**H.8 Transfer threshold** (`recommend.py`). Compare two plans:

- the plan with transfers allowed
- the "roll" plan: no transfer this GW, transfers allowed later

Transfer only if the gain is at least the threshold (default 2 points over the horizon).

**H.9 Free-transfer rollover:**

```
normal week:   free[g+1] = min(5, max(0, free[g] − used[g]) + 1)
WC/FH week:    free[g+1] = free[g]
```

In the MILP, `max(0, ·)` needs one binary per GW. `min()` needs only upper bounds, plus a tiny
bonus per FT so that the reported count is exact.

**H.10 Chips** (`optimise/chips.py`). For each GW up to 19, using your current squad:

- TC = captain EP
- BB = bench EP
- FH = best legal squad's XI EP − your XI EP

Plan each chip for its best GW. Rerun weekly, and play any unused chip by GW19.

---

## I. Reference numbers (replay, 2025/26)

**Points, GW5–38** (`fpl backtest --model …`):

| Model                       | Pool R RMSE / bias / ρ  | Pool O RMSE / bias / ρ  | Top 15: projected v realised |
| --------------------------- | ----------------------- | ----------------------- | ---------------------------- |
| ep_next (FPL)               | 3.43 / +0.28 / 0.28     | 3.37 / +0.09 / 0.50     | 7.96 v 4.34                  |
| blend                       | 3.19 / +0.22 / 0.30     | 3.12 / +0.22 / 0.52     | 6.58 v 4.39                  |
| **shrunk_blend** (skeleton) | **3.12 / −0.03 / 0.32** | **3.05 / −0.02 / 0.53** | **5.71 v 4.48**              |

**Points, GW20–38.** The full model is trained on GW2–19 only:

| Model        | Pool R                  | Pool O                  | Top 15          |
| ------------ | ----------------------- | ----------------------- | --------------- |
| shrunk_blend | 3.07 / 0.00 / 0.33      | 3.00 / +0.01 / 0.54     | 5.87 v 4.58     |
| **full**     | **3.00 / +0.12 / 0.39** | **2.93 / +0.01 / 0.58** | **5.89 v 4.80** |

The full model passes the gate:

- lower RMSE and higher ρ in both pools
- smaller top-15 over-projection (1.09 v 1.29)

**Minutes, P(60+), log loss, test GW20–38:**

| Model                  |  Log loss |
| ---------------------- | --------: |
| constant               |     0.567 |
| started last GW        |     0.339 |
| started last GW × flag |     0.285 |
| **minutes model**      | **0.250** |

**Clean sheets, Brier score, GW5–38:**

| Source                 |                         Brier | Skill over a constant rate |
| ---------------------- | ----------------------------: | -------------------------: |
| odds, next GW          | 0.1699 (constant rate 0.1815) |                       6.4% |
| ratings, 1–5 GWs ahead |                   0.176–0.179 |                   3.9–6.1% |

---

## J. GW6 calendar

Kigali is UTC+2 all year.

| UTC                        | Kigali              | Event                                                                                      | Action                                               |
| -------------------------- | ------------------- | ------------------------------------------------------------------------------------------ | ---------------------------------------------------- |
| 21 Sep – 6 Oct             |                     | FIFA window: up to 4 matches per player; the last South American games are on 6 Oct \[16\] | watch `news` for international injuries              |
| daily 23:00                | 01:00               | price change                                                                               |                                                      |
| Thu 8 – Fri 9 Oct          |                     | press conferences                                                                          |                                                      |
| Fri 9 Oct, afternoon       |                     | GW6 odds appear in football-data `fixtures.csv`                                            | `fpl odds`                                           |
| **Fri 9 Oct, 17:30–22:30** | **19:30–Sat 00:30** | **final run 1**                                                                            | **make transfers before the 23:00 UTC price change** |
| Sat 10 Oct, 08:00–09:30    | 10:00–11:30         | final run 2                                                                                | captain, bench, late news only                       |
| **Sat 10 Oct, 10:00**      | **12:00**           | **GW6 deadline**                                                                           |                                                      |
| Tue 13 Oct, after 08:00    | after 10:00         | scoring lock                                                                               | `fpl update && fpl settle`                           |
| Sat 17 Oct, 10:00          | 12:00               | GW7 deadline                                                                               |                                                      |

---

## K. Deferred LLM and deployment work

Part 3 says when and how to add these without changing the deterministic projection and solver
boundary.

- **A read-only conversational layer.** It chooses typed FPL tools and explains their output. It
  does not run arbitrary SQL, calculate expected points or make transfers.
- **An LLM news layer.** It outputs fixed categories with a verbatim quote, never probabilities,
  because verbalised LLM confidence is overconfident \[17\]. Ollama supports tool calling,
  `tool_choice` and schema-based structured output. Validate every structured reply and every
  quotation in application code \[18\].
- **A server, Docker and cron.** On a laptop, run `fpl update` when you work.
- **An agent framework or auto-submission.** The first agent loop is small enough to write
  directly, and transfer submission remains a manual action.
- **A web UI.** Add it only after the CLI agent and its evaluations are stable. It must call the
  same application service as the CLI.

---

## References

\[1\] T. Gneiting, "Making and evaluating point forecasts," _J. Amer. Statist. Assoc._, vol. 106,
no. 494, pp. 746–762, 2011, doi: 10.1198/jasa.2011.r10138.

\[2\] J. E. Smith and R. L. Winkler, "The optimizer's curse: Skepticism and postdecision surprise
in decision analysis," _Manage. Sci._, vol. 52, no. 3, pp. 311–322, 2006,
doi: 10.1287/mnsc.1050.0451.

\[3\] OneFPL, "FPL bonus points system changes for 2026/27."
https://onefpl.com/blog/fpl-bonus-points-system-changes

\[4\] Premier League, "All you need to know about changes to FPL for 2026/27," 31 Jul. 2026.
https://www.premierleague.com/en/news/4679873/all-you-need-to-know-about-changes-to-fpl-for-202627

\[5\] Fantasy Premier League, "Rules." https://fantasy.premierleague.com/help/rules

\[6\] Premier League, "What's new in 2026/27 Fantasy: Price Change Predictor," 22 Aug. 2026.
https://www.premierleague.com/en/news/4680462/whats-new-in-202627-fantasy-price-change-predictor

\[7\] Randdalf, "fplcache." https://github.com/Randdalf/fplcache

\[8\] V. Anand, "Fantasy-Premier-League." https://github.com/vaastav/Fantasy-Premier-League

\[9\] Football-Data.co.uk, results and odds, and notes. https://www.football-data.co.uk/notes.txt

\[10\] Fantasy Football Scout, "Team news." https://www.fantasyfootballscout.co.uk/team-news

\[11\] RotoWire, "Soccer lineups." https://www.rotowire.com/soccer/lineups.php

\[12\] Sports Reference, "FBref and Stathead data update," 20 Jan. 2026.
https://www.sports-reference.com/blog/2026/01/fbref-stathead-data-update/

\[13\] D. Forrest, J. Goddard, and R. Simmons, "Odds-setters as forecasters: The case of English
football," _Int. J. Forecast._, vol. 21, no. 3, pp. 551–564, 2005,
doi: 10.1016/j.ijforecast.2005.03.003.

\[14\] E. Štrumbelj, "On determining probability forecasts from betting odds," _Int. J. Forecast._,
vol. 30, no. 4, pp. 934–943, 2014, doi: 10.1016/j.ijforecast.2014.02.008.

\[15\] M. J. Maher, "Modelling association football scores," _Statistica Neerlandica_, vol. 36,
no. 3, pp. 109–118, 1982, doi: 10.1111/j.1467-9574.1982.tb00782.x.

\[16\] FIFA, "Men's international match calendar 2023–2030."
https://digitalhub.fifa.com/m/3123d37097318f7f/original/Men-s-International-Match-Calendar-2023-2030_EN.pdf

\[17\] M. Xiong et al., "Can LLMs express their uncertainty? An empirical evaluation of confidence
elicitation in LLMs," in _Proc. ICLR_, 2024. arXiv:2306.13063.

\[18\] Ollama, "Tool calling," "Structured outputs" and "OpenAI compatibility."
https://docs.ollama.com/capabilities/tool-calling,
https://docs.ollama.com/capabilities/structured-outputs,
https://docs.ollama.com/api/openai-compatibility
