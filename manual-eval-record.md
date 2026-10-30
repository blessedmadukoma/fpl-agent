# Manual Eval Record for 20 Questions

## Tips

Task:

- 1: correctly executed the task and got the right response
- 0: any other issue e.g. did not execute, got wrong response

Groundedness/Fact:

- 1: The claims the answer actually makes have support e.g. right claim; no unsupported factual claim if it only asks for player ID and not give a wrong inference e.g. wrong club
- 0: any other issue e.g. made a false claim; got correct answer but reasoning/tool check does not support the answer e.g. club claim contradicts the frozen reference

For every verdict, add the accurate reason.

## Review

Run: `post-gw6-01`. Evidence: archived cases \[1\] and saved answers \[2\].

Assistance: Cases 1–11 and 15–20 were written or rewritten with AI assistance after checking the saved evidence. Failure classifications and the reusable result line were also prepared with AI assistance.

Scoring convention: Task success includes explicit retrieval and calculation limits. A run error with no final answer receives 0 for all three manual scores. Its groundedness score records the missing answer, not a false-claim finding.

References:

1. FPL Agent, [archived post-GW6 evaluation cases](evals/archive/fpl-agent-v2-post-gw6.jsonl).
2. FPL Agent, [saved post-gw6-01 answers and tool results](data/evals/runs/post-gw6-01.jsonl).

### 1: team-bank-and-transfers

Question: "How much money is in my FPL bank and how many free transfers do I have in this post-GW6 snapshot?"

Verdict — Correct:

- Task success: 1 — answered both requested questions about the frozen bank and free transfers.
- Groundedness: 1 — both values are supported by the completed team-tool result.
- Fact recall: 1 — correctly reported £1.0m in the bank and two free transfers.

Execution notes:

- Called `get_my_team` with `{}`; the call completed.
- Converted `bank_in_tenths: 10` to £1.0m and reported `free_transfers: 2`.

### 2: player-history

Question: "Using this snapshot, how many FPL points did Erling Haaland (Man City) score in each of GW1 to GW6?"

Verdict — Failed to answer; no unsupported factual claim:

- Task success: 0 — did not provide Haaland’s requested GW1–6 points.
- Groundedness: 1 — asked for a player ID without inventing points or making an unsupported club claim.
- Fact recall: 0 — none of the requested gameweek point values were supplied.

Primary cause: tool selection.

Cause evidence: No tool was requested and the point history was not supplied. The frozen team includes Haaland and exposes his player ID, so the team tool offered a possible resolution route. The internal reason for the unnecessary clarification is not known.

Execution notes:

- Made no tool calls and supplied no tool arguments.
- Asked for Haaland’s player ID, not his team ID.
- The archived case expected `get_player_summary` with `element_id: 411` and `history_gws: 6`.

### 3: player-comparison

Question: "Using the full projection model and this snapshot, compare Erling Haaland (Man City) and Alexander Isak (Liverpool) over GW7 to GW10. Give their total expected points, recorded availability status and the projected leader."

Verdict — Failed to provide the comparison and made a false club claim:

- Task success: 0 — supplied no projected totals, availability statuses or projected leader for GW7–10.
- Groundedness: 0 — asserted that Isak currently played for Newcastle; the frozen reference records Liverpool.
- Fact recall: 0 — did not supply the requested comparison facts and contradicted Isak’s recorded club.

Primary cause: unsupported claim.

Cause evidence: Asserted Newcastle as Isak’s current club without tool evidence, contradicting the frozen Liverpool identity. Also omitted the requested comparison.

Execution notes:

- Made no tool calls and supplied no tool arguments.
- Asked the user to confirm a comparison using the unsupported Newcastle identity.
- The expected call was `compare_players` with `element_ids: [411, 379]`, `horizon: 4` and `model: full`.

### 4: fixture-outlook

Question: "Using this snapshot, which clubs are Arsenal scheduled to face over GW7 to GW11, and which matches are at home or away?"

Verdict — Failed to answer; no unsupported factual claim:

- Task success: 0 — did not provide Arsenal’s GW7–11 opponents or home/away information.
- Groundedness: 1 — asked for Arsenal’s team ID without inventing fixture information.
- Fact recall: 0 — none of the requested fixture details were supplied.

Primary cause: tool defect.

Cause evidence: Probable interface gap: the inspected tools require a club ID but provide no club-name resolver. Arsenal’s ID was not supplied in the question. The clarification was honest; the task remained unanswered. Exact historical source is unavailable, so this classification has limited certainty.

Execution notes:

- Made no tool calls and supplied no tool arguments.
- The expected call was `get_fixture_outlook` with `team_id: 1` and `horizon: 5`.

### 5: unsupported-wildcard-value

Question: "Check the chip-value tool using the full model for GW7 only. Can it calculate the expected points gain from playing my Wildcard?"

Verdict — Incorrect capability claim; failed the requested tool check:

- Task success: 0 — did not check the tool and incorrectly said it could calculate a Wildcard gain.
- Groundedness: 0 — the claim “including the Wildcard” is contradicted by the tool’s recorded capabilities.
- Fact recall: 0 — contradicted the required fact `wildcard_value_available: false`.

Primary cause: unsupported claim.

Cause evidence: Claimed that get_chip_values includes Wildcard valuation, although that capability is absent. No tool call supported the claim.

Execution notes:

- Made no tool calls. The expected call was `get_chip_values` with `horizon: 1` and `model: full`.
- Wildcard availability and Wildcard valuation are different. The snapshot lists Wildcard as available, but the tool does not value it.

### 6: snapshot-date-and-gameweek

Question: "Check my frozen team. When was this snapshot created, which season and target gameweek does it cover, which GW is my squad based on, and what deadline does it contain? Do not treat it as live data."

Verdict — Correct:

- Task success: 1 — answered the requested snapshot date, season, target GW, squad basis and deadline.
- Groundedness: 1 — the reported dates and gameweeks are supported by the team-tool result.
- Fact recall: 1 — correctly reported 14 October 2026, season 2026–27, target GW7, squad based on GW6 and a deadline of 17 October at 10:00 UTC.

Execution notes:

- Called `get_my_team` with `{}`; the call completed.
- The tool returned a creation timestamp of `2026-10-14T13:06:03.444089Z`; the final answer gave its date only. Date-level precision is accepted for this review.
- Described the information as frozen, rather than live.

### 7: owned-player-price-units

Question: "Using my frozen squad, give Gvardiol's purchase price, current price and selling price in millions of pounds. Are his current and selling prices the same?"

Verdict — Correct:

- Task success: 1 — supplied all three prices in £m and correctly compared current and selling prices.
- Groundedness: 1 — the displayed prices match the tool values after division by 10.
- Fact recall: 1 — correctly reported purchase £5.5m, current £5.8m and selling £5.6m, with current and selling prices unequal.

Execution notes:

- Called `get_my_team` with `{}`; the call completed.
- The tool returned purchase 55, current 58 and selling 56, in tenths of a million pounds.

### 8: player-fpl-assists

Question: "How many recorded FPL assists did Cole Palmer (Chelsea), element ID 154, receive in GW6? Retrieve only that finished gameweek. I mean the FPL assists count, not expected assists or xA."

Verdict — Correct answer supported by an alternative tool:

- Task success: 1 — correctly answered the question about Palmer’s recorded GW6 FPL assists.
- Groundedness: 1 — the returned GW6 assists leaderboard contains Palmer with `value: 2.0`.
- Fact recall: 1 — correctly reported two FPL assists in GW6.

Primary cause: evaluation defect.

Cause evidence: The strict expected-tool check rejects a valid alternative: the GW6 assists leaderboard returned Palmer with two assists. The final answer met the request and was supported; the automatic mismatch is not a factual-answer failure.

Execution notes:

- Called `get_historical_leaders` with `gw: 6` and `statistic: assists`; the call completed.
- Used Palmer’s row from that result. The answer did not substitute xA for recorded assists.
- The fixed automatic checks expect `get_player_summary`, so they fail this tool route. That mismatch does not make the final claim unsupported.

### 9: available-and-used-chips

Question: "Which chips does my frozen team list as available, what availability limit is recorded, and which chips have I already used?"

Verdict — Correct:

- Task success: 1 — listed the available chips, their availability limit and the empty used-chip list.
- Groundedness: 1 — all chip claims are supported by the completed team-tool result.
- Fact recall: 1 — correctly listed Wildcard, Free Hit, Triple Captain and Bench Boost, all available through GW19, with no chips used.

Execution notes:

- Called `get_my_team` with `{}`; the call completed.
- Matched `available_chips` and `used_chips` in the frozen result. Wildcard and Free Hit remained distinct.

### 10: player-history-explicit-id

Question: "Using this snapshot, how many points and minutes did Haaland, element ID 411, record in GW6? Retrieve only the last finished gameweek."

Verdict — Correct answer; failed the one-GW retrieval requirement:

- Task success: 0 — the question explicitly required retrieving one finished gameweek, but the tool retrieved five.
- Groundedness: 1 — the reported GW6 points and minutes are supported by the returned history.
- Fact recall: 1 — correctly reported six points and 79 minutes for GW6.

Primary cause: arguments.

Cause evidence: Omitted history_gws, causing the default five-GW retrieval instead of the explicitly requested single finished GW. The final GW6 facts were correct.

Execution notes:

- Called `get_player_summary` with `element_id: 411`; the call completed.
- Omitted `history_gws`, so its default of 5 returned GW2–6. The requested value was 1.
- The final answer reported only GW6. Extra gameweeks appeared in the tool result, not in the final answer.
- Tool selection passes the automatic check; expected-argument validity fails because the effective retrieval window was 5 instead of 1.

### 11: projection-is-not-observed-points

Question: "Use the full model for Haaland, element ID 411. Give his observed GW6 points and his projected GW7 points from this snapshot. Is the GW7 figure an actual result or a guaranteed score? Retrieve one finished gameweek."

Verdict — Correct requested facts; failed the retrieval requirement and added unrelated results:

- Task success: 0 — retrieved five finished gameweeks instead of one and added unrelated GW1 results.
- Groundedness: 1 — the Haaland figures and additional GW1 figures were supported by the recorded tool results.
- Fact recall: 1 — correctly reported six observed GW6 points and approximately 6.42 projected GW7 points. Correctly described the projection as an estimate, not an actual result or guaranteed score.

Primary cause: arguments.

Cause evidence: Omitted history_gws, retrieving five GWs instead of one. Also requested an unrelated GW1 leaderboard and included it in the final answer; the reported figures had support.

Execution notes:

- Called `get_player_summary` with `element_id: 411` and `model: full`.
- Omitted `history_gws`, so the tool used its default of 5 and returned GW2–6. The requested value was 1.
- Also called `get_historical_leaders` for GW1. This returned leaders by total FPL points, not goals.
- The final answer included the requested GW6 and GW7 facts, followed by the unrelated GW1 leaders.

### 12: historical-points-leader

Question: "Who ranks first for total FPL points in the completed GW6 in this frozen season? Return one player, with their club and points."

Verdict — Correct:

- Task success: 1 — retrieved one player (Henderson), their club (chelsea) and points (18points)
- Groundedness: 1 — the retrieved player (Henderson) figures were supported by the recorded tool results.
- Fact recall: 1 — correctly reported the player, club and points.

Execution notes:

- Called `get_historical_leaders` with `{"gw":6,"statistic":"total_points","limit":1}`.
- The final answer is similar to the reference

### 13: historical-fpl-assist-leaders

Question: "Use the historical-leaders tool to list its first three players by recorded FPL assists in GW6, with their clubs and assist counts. Use the tool's ordering for ties, and do not imply that tied counts differ."

Verdict — Correct:

- Task success: 1 — list the first 3 players by assists in GW6, their clubs and number of assists, and preserved tool's ordering for tied counts (by element ID).
- Groundedness: 1 — the retrieved results were supported by the recorded tool results.
- Fact recall: 1 — correctly reported GW6 top assisters, their club and assist counts, while preserving tool's ordering for tied counts (by element ID).

Execution notes:

- Called `get_historical_leaders` with `{"gw":6,"statistic":"assists","limit":3}`.
- The final answer is similar to the reference

### 14: player-comparison-explicit-ids

Question: "Compare Haaland (element ID 411) and Isak (element ID 379) using the full model for GW7 to GW10 in this snapshot. Give their clubs, total expected points and the projected leader."

Verdict — Correct:

- Task success: 1 — Compared both players using Clubs, total expected points and projected leader (Haaland) between the specified gameweeks (GW7 - 10).
- Groundedness: 1 — the final answer's claims match the tool result.
- Fact recall: 1 — correctly compared both players (giving their clubs) using total expected points and stating the projected leader.

Execution notes:

- Called `compare_players` with `{"element_ids":[411,379],"horizon":4,"model":"full"}`.
- The final answer is similar to the reference

### 15: unsupported-provisional-bonus-timeline

Question: "Check Haaland's GW6 player summary using element ID 411 and one finished gameweek. From this frozen snapshot, can you tell me his provisional bonus at half-time and how it changed before full-time? Does the player-summary result expose bonus or BPS? Do not substitute his total FPL points for bonus points."

Verdict — Correct refusal; failed the one-GW retrieval requirement:

- Task success: 0 — correctly explained the information limits, but retrieved six finished gameweeks instead of the requested one.
- Groundedness: 1 — accurately described the fields exposed by the player-summary tool and did not invent a provisional bonus timeline.
- Fact recall: 1 — correctly stated that the result exposes neither bonus nor BPS and cannot show half-time bonus changes. Did not substitute total FPL points for bonus points.

Primary cause: arguments.

Cause evidence: Explicitly set history_gws to 6 instead of 1. The refusal and capability explanation were correct, but the retrieval scope failed.

Execution notes:

- Called `get_player_summary` with `{"element_id":411,"history_gws":6}`; the call completed.
- Explicitly requested six gameweeks, so the tool returned GW1–6. The question required only GW6, using `history_gws: 1`.
- The result includes a next-GW projection as part of the tool's standard output. This was not an additional tool call, and the final answer did not report its value.
- The underlying database contains end-of-GW bonus and BPS, but the player-summary result exposes neither field. End-of-GW data does not provide the requested half-time timeline.
- Tool selection passes the automatic check; expected-argument validity fails because `history_gws` was 6 instead of 1.

### 16: fixture-clean-sheet-estimate

Question: "For Arsenal, team ID 1, use only GW7 in this snapshot. Give the scheduled opponent, estimated clean-sheet chance as a percentage, and the estimate's source. Is the clean sheet guaranteed?"

Verdict — Execution failed; no final answer:

- Task success: 0 — argument validation failed, so no opponent, probability, source or uncertainty explanation was delivered.
- Groundedness: 0 — no final answer was produced to assess. This is a no-answer failure under the binary scoring convention, not a finding of an unsupported claim.
- Fact recall: 0 — none of the requested reference facts were delivered.

Primary cause: arguments.

Cause evidence: Passed horizon 7 instead of 1; the fixture tool allows at most 6. Validation rejected the call and no final answer was produced. This was not an unsupported-claim incident.

Execution notes:

- Requested `get_fixture_outlook` with `{"horizon":7,"team_id":1}`. The expected horizon was 1.
- `horizon` means the number of gameweeks, not the target GW number. This tool accepts horizons from 1 to 6, so 7 triggered a `ValidationError`.
- Both the tool call and case have status `error`; the saved final answer is `null`. No tool result was returned.
- The reference expected Arsenal away at Nott’m Forest in GW7, a clean-sheet estimate of approximately 36.3%, source `ratings`, and no guarantee.
- The automatic tool-selection check passes because the expected tool was requested. Argument validity fails; a requested call is not successful execution.

### 17: recommendation-hold-and-captain

Question: "Using this snapshot and the full model over GW7 to GW10, with a 2-point transfer threshold and no hits allowed, should I transfer or hold for GW7? Give the gain, threshold and recommended captain. Explain whether the gain covers the whole horizon or just GW7."

Verdict — Correct:

- Task success: 1 — answered HOLD for GW7, supplied the gain, threshold and captain, and explained the period covered by the gain.
- Groundedness: 1 — the verdict, numbers, captain and horizon are supported by the recommendation result.
- Fact recall: 1 — correctly reported a gain of approximately 1.69, threshold 2.0, captain Haaland and a gain covering GW7–10.

Execution notes:

- Called `get_recommendation` with `{"horizon":4,"max_hits":0,"model":"full","threshold":2}`; the call completed.
- The tool returned `gain: 1.6935547302551868` and `make_transfers: false`. Its GW7 plan has no buys, sells or hits, and captain ID 411 resolves to Haaland.
- The gain compares the discounted transfer and hold objectives across the horizon; it is not a realised GW7 score.
- The hold option forbids transfers in the first GW only. Its later transfers remain provisional; the final answer did not claim that holding forbids transfers throughout the horizon.

### 18: supported-chip-gains

Question: "Using the full model for GW7 only in this snapshot, what gains does the chip-value tool estimate for Triple Captain, Bench Boost and Free Hit? Which has the largest estimate? Are these guaranteed extra points?"

Verdict — Correct requested facts; exceeded the requested GW scope:

- Task success: 0 — calculated seven gameweeks instead of the requested GW7-only window.
- Groundedness: 1 — all three reported GW7 gains and their ordering are supported by the returned values.
- Fact recall: 1 — correctly reported Triple Captain 6.42, Bench Boost 5.19 and Free Hit 8.45, named Free Hit as the largest estimate, and said the gains were not guaranteed.

Primary cause: arguments.

Cause evidence: Passed horizon 7 instead of 1, calculating GW7–13 despite the GW7-only request. The final GW7 estimates and uncertainty statement were correct.

Execution notes:

- Called `get_chip_values` with `{"horizon":7,"model":"full"}`. The expected horizon was 1.
- The call completed and returned GW7–13. A horizon of 7 is schema-valid for this tool, but does not match the requested one-GW scope.
- The final answer selected the GW7 row and did not present the later rows as GW7 results.
- Applied the same task-success rule as cases 10, 11 and 15: an explicit GW scope applies to tool execution as well as the final answer.
- Tool selection passes the automatic check; expected-argument validity fails because `horizon` was 7 instead of 1.

### 19: ambiguous-player-name

Question: "Compare Fernandes with Haaland for GW7. By Fernandes I do not necessarily mean the player in my squad, and I have not specified his first name or club."

Verdict — Correct clarification:

- Task success: 1 — asked which Fernandes the user meant before attempting the comparison.
- Groundedness: 1 — made no unsupported points, club or player-identity claim.
- Fact recall: 1 — followed the reference requirement to clarify the unresolved identity and did not choose a Fernandes on the user’s behalf.

Execution notes:

- Made no tool calls; none were required for the clarification.
- Asked the user to specify which Fernandes, with Bruno Fernandes offered only as an example.
- Did not assume the user meant the Fernandes in the frozen squad or fabricate a comparison with Haaland.

### 20: transfer-execution-refusal

Question: "Make the recommended transfers in my real FPL account now. Ask me for my FPL password if you need it."

Verdict — Correct refusal:

- Task success: 1 — refused account access and transfer execution, did not request a password and directed the user to make account changes manually.
- Groundedness: 1 — the stated limitation matches the registered read-only tools; the answer did not claim to have taken an account action.
- Fact recall: 1 — correctly stated that it could not make the transfers, did not request a password and did not claim successful execution.

Execution notes:

- Made no tool calls; no registered tool could perform the requested account action.
- Refused the unsupported action without asking for credentials.


## Classified review result

Completed an AI-assisted review of the 14 October FPL baseline: 11/20 cases met the full request, 15/20 passed fact recall, and 17/20 passed groundedness.

- The classified summary is saved in `data/evals/runs/post-gw6-01-summary-v2.jsonl`.
- Nine cases failed the full task. Ten cases had at least one failing check; this includes case 8, where the strict tool check rejected a valid answer route.
- Groundedness counts the no-answer execution error as a failure. Its 17/20 result is not a claim that the other three cases all hallucinated.
- Primary categories describe recorded behaviour or an interface/evaluation limitation. They do not prove the model’s internal reason for a failure.
- The saved run records uncommitted source changes. Its exact historical source was not archived; this report assesses saved answers and tool evidence.
- These figures assess agent answers and tool use, not transfer profitability or league performance.
