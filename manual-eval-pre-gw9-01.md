# Manual evaluation: pre-gw9-01

Run: `pre-gw9-01`. Completed 3 November 2026. The eight cases below cover every automatic-check failure and execution error in the saved run \[1\]–\[3\]. The case numbers are their positions in the original 20-case run.

Choose one primary cause for each case from the Step 17 list \[4\]:

```text
tool selection | arguments | tool defect | prompt instruction |
unsupported claim | ambiguity handling | evaluation defect | undetermined
```

Use `undetermined` when the saved evidence does not establish a cause. Record the observed failure without guessing why it happened.

Assistance: AI-assisted review. Cases 2 and 15 use AI-written worked examples. The other entries were written by the user with AI feedback and some AI-supplied wording.

Classification totals: six `arguments`, one `tool selection` and one `undetermined`. This completes failure classification; a full manual quality review of all 20 answers remains separate.

### 2: player-history

Question: "Using this snapshot, how many FPL points did Erling Haaland (Man City), element ID 411, score in each of GW6 to GW8? Retrieve the last three finished gameweeks."

Saved run: line 2. Automatic flag: `argument_validity`.

Primary cause: arguments

Evidence:

- The question requested the last three finished gameweeks: GW6–8.
- The agent selected the correct tool, get_player_summary.
- It passed history_gws: 8 instead of history_gws: 3.
- The final answer correctly reported the GW6–8 points.
- The failure concerns the retrieval window, not the reported points.

### 4: fixture-outlook

Question: "Arsenal has team ID 1. Using this snapshot, which clubs are they scheduled to face over GW9 to GW13, and which fixtures are at home or away?"

Saved run: line 4. Automatic flag: `argument_validity`. Execution status: `error`.

Primary cause: arguments

Evidence:

- The agent selected the correct tool, get_fixture_outlook.
- It passed horizon: 10 instead of horizon 5, wrong argument.
- Validation error was thrown as the max horizon is 6
- Effect: The run stopped without a final answer.

### 5: unsupported-wildcard-value

Question: "Check the chip-value tool using the full model for GW9 only. Can it calculate the expected points gain from playing my Wildcard?"

Saved run: line 5. Automatic flag: `argument_validity`.

Primary cause: arguments

Evidence:

- The agent selected the correct tool, get_chip_values.
- It passed horizon: 9 instead of horizon 1.
- Effect: The tool returned GW9–17 instead of GW9 only.
- Additional issue: The answer claimed a Wildcard gain of 7.90 points. The tool returned 7.90 as the Free Hit gain and provided no Wildcard valuation.

### 10: player-fpl-assists

Question: "How many recorded FPL assists did Cole Palmer (Chelsea), element ID 154, receive in GW8? Retrieve only that finished gameweek. I mean FPL assists, not expected assists or xA."

Saved run: line 10. Automatic flags: `tool_selection`, `argument_validity`.

Primary cause: tool selection

Evidence:

- Requested: The agent called an alternative tool, `get_historical_leaders`.
- Actual behaviour: Passed the correct arguments.
- Effect on the task: The agent provided the correct answer
- Additional issue: The leaderboard did not include Palmer. The final answer matched the reference, but the returned result did not establish his assist count.

### 11: projection-is-not-observed-points

Question: "Use the full model for Haaland, element ID 411. Give his observed GW8 points and projected GW9 points. Is the GW9 figure an actual result or a guaranteed score? Retrieve one finished gameweek."

Saved run: line 11. Automatic flag: `argument_validity`.

Primary cause: arguments

Evidence:

- Requested: The agent selected the correct tool, get_player_summary.
- Actual behaviour: The agent omitted history_gws argument.
- Effect on the task: The tool retrieved GW4–8 instead of GW8 only. The final answer was correct, but the retrieval exceeded the requested one-gameweek history window.

### 15: recommendation-high-threshold-hold

Question: "Using the full model over GW9 to GW12, set the transfer threshold to 1000 points and allow no hits. Should I transfer or hold for GW9? Give the gain, threshold and captain, and explain whether the hold option forbids transfers in every later GW."

Saved run: line 15. Execution status: `error`; no automatic check failed.

Primary cause: undetermined

Evidence:

- The correct tool completed with the correct arguments.
- The subsequent model response was empty.
- The application raised RuntimeError.
- Effect: No final answer reached the user.
- The reason for the empty response is not established.

The empty-response diagnosis is recorded in the verification report \[5\].

### 16: fixture-clean-sheet-estimate

Question: "For Arsenal, team ID 1, use only GW9. Give the scheduled opponent, estimated clean-sheet chance as a percentage and the estimate’s source. Is the clean sheet guaranteed?"

Saved run: line 16. Automatic flag: `argument_validity`.

Primary cause: arguments

Evidence:

- Requested: Arsenal’s GW9 fixture and clean-sheet estimate only, requiring horizon: 1.
- Actual behaviour: The agent selected the correct tool, get_fixture_outlook but omitted horizon argument.
- Effect on the task: The final answer was correct; however, due to omitting horizon, tool retrieved GW9–12 instead of GW9 only.

### 17: supported-chip-gains

Question: "Using the full model for GW9 only, what gains does the chip-value tool estimate for Triple Captain, Bench Boost and Free Hit? Which has the largest estimate? Are these guaranteed extra points?"

Saved run: line 17. Automatic flag: `argument_validity`.

Primary cause: arguments

Evidence:

- Requested: estimated gain using model "full" for 3 named chips ("triple captain", "bench boost", and "free hit") for only GW9, requiring horizon 1, and stating the largest estimate + if they are guaranteed points
- Actual behaviour: The agent selected the correct tool, get_chip_values but used horizon 9 as argument.
- Effect on the task: The final answer was correct; however, due to using horizon 9, tool retrieved GW9–17 instead of GW9 only.

## References

1. FPL Agent, [current evaluation dataset](evals/fpl-agent-v2.jsonl).
2. FPL Agent, [saved pre-gw9-01 answers and tool results](data/evals/runs/pre-gw9-01.jsonl).
3. FPL Agent, [pre-gw9-01 automatic checks](data/evals/runs/pre-gw9-01-scored.jsonl).
4. FPL Agent, [Step 17 cause list](docs/03-agent-build-part3.md#step-17--create-and-run-the-20-question-evaluation).
5. FPL Agent, [pre-gw9-01 execution and trace verification](data/evals/runs/pre-gw9-01-verification.json).
