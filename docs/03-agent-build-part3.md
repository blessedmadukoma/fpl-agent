# FPL Agent — Build, Part 3: frozen data, an LLM layer, traces and evals

Version 13, 5 November 2026. This guide starts at Step 13, immediately after Part 2. It adds a
read-only conversational agent around the existing FPL calculations. It then adds tracing, a
fixed evaluation set, a pilot with real users, the early-season backtest and the news extractor.

**Current route:** the archived Step 17 review and both runs' failure classifications are
complete. The GW9 baseline has saved results and verified traces. Keep the personal weekly
FPL workflow active for the December league goal. The new answers still need a separate
quality review before reporting their full-task or groundedness scores.
Use [Part 3: understand and own the implementation](03-agent-build-part3-learning.md) for
the review work and `budget-system` for new agent implementation practice. The public pilot
is postponed. Learning checks remain separate from software status.

**Changed in version 6:** refresh the active 20-case dataset from a post-GW8 snapshot,
preserve the old dataset for its saved run, and add the league goal. Question and reference
preparation is explicitly delegated to AI. The commit is part of Step 17.

**Changed in version 7:** include explicit chip timing in recommendations. Prompt version 2
requires the agent to report that decision and its limits. This implementation was delegated
to AI; it does not complete any learner understanding check.

**Changed in version 8:** set the top-10 checkpoints for 1, 15 and 30 December.
Keep each checkpoint's outcome even if the target is reached at a later date.

**Changed in version 9:** complete the GW9 failure classification, keep each run's review
in a separate file, and allow `undetermined` when the saved evidence cannot establish a cause.

**Changed in version 10:** Step 19 tests the temperature in a second stage and adds answer
checks. Step 21 ships the web page in three releases: read-only pages, live questions for the
owner, then a public "try your team ID" page with limits and protections (21.4). Login,
visitors' own API keys, payments and a model choice per visitor are later work.

**Changed in version 11:** define an unsupported number for rule 1 of Step 19. The definition
was written after the first screening flags were read.

**Changed in version 12:** record the Step 19 outcome. No model met the rule; `glm-5.3:cloud` at
temperature 0 is the provisional pilot model.

**Changed in version 13:** the open Step 19 checks (a run for the last tool change, task success,
cost and latency) move to before release 1 of Step 21.

**Changed in version 5:** add a separate learning-first route and a user-wide, cross-agent
Socratic mentor skill. Keep the delivery steps and their order. Do not restart implemented work
or change the user's current todo.

**Changed in version 4:** deploy the server and a small web page in Step 21, then run the
real-user pilot in Step 22. Telegram is optional in Step 23 and does not delay the pilot.
Steps 13–20 are unchanged. The early-season backtest remains Step 24, the news workflow Step 25
and the backlog Step 26.

This is a build guide, not a code listing. Write the implementation yourself. Use the interfaces,
tests and checkpoints below to decide whether each step is complete.

The LLM has two separate jobs:

1. **Conversational agent:** choose a safe FPL tool and explain its deterministic result.
2. **News extractor:** turn retrieved manager quotations into fixed availability claims.

The LLM must not calculate expected points, optimise transfers, run arbitrary SQL or make changes
on the FPL website. The existing Python models and optimiser remain the source of every number.
A later user interface must call the same agent service as the CLI. Do not put FPL logic in the UI.

| Step | Adds                                      | Tangible result                                      |
| ---- | ----------------------------------------- | ---------------------------------------------------- |
| 13   | an immutable evaluation snapshot          | repeated runs use identical FPL data                 |
| 14   | typed, read-only FPL tools                | deterministic JSON without an LLM                    |
| 15   | an Ollama tool-calling loop               | `fpl ask "…"` answers grounded FPL questions        |
| 16   | Langfuse tracing and prompt versions      | one complete trace for every question                |
| 17   | 20 fixed evaluation cases                 | a reproducible baseline with named failure causes    |
| 18   | one controlled prompt or tool change      | a before/after table from the same evaluation set    |
| 19   | the pilot model, chosen by the same cases | a model table with scores, cost and latency          |
| 20   | each user's team from live snapshots      | `fpl ask --entry <id>` works for any public entry    |
| 21   | a server and the web page, in three releases | read-only pages, then owner questions, then public team IDs with limits |
| 22   | the pilot with real users, GW10–GW14        | a write-up with numbers from real traces             |
| 23   | an optional Telegram interface            | another client over the tested service               |
| 24   | the early-season backtest                 | a GW5–19 test with previous-season priors            |
| 25   | the Tavily and Ollama news workflow       | cited manager claims that can affect minutes safely  |
| 26   | the remaining model backlog               | ordered work after the measured agent changes        |
---

## Personal league goal — December 2026

**Target:** reach the top 10 of my private mini-league.

Check progress on these dates. If the target is missed at an earlier checkpoint,
continue towards the next one. Record all three outcomes; a later success does
not replace an earlier result.

| Checkpoint | Date | League rank | Gap to tenth | Target met? |
| --- | --- | --- | --- | --- |
| Primary target | 1 December 2026 | Pending | Pending | Pending |
| Second checkpoint | 15 December 2026 | Pending | Pending | Pending |
| Final checkpoint | 30 December 2026 | Pending | Pending | Pending |

Use the latest official standings at each checkpoint. Record the lookup time
and gameweek so the result has a clear date.

Starting position checked on 28 October 2026, after GW8 \[15\]:

| Completed GW | League rank | Total points | Tenth-place points | Gap to tenth |
| --- | --- | --- | --- | --- |
| 8 | 28 | 471 | 519 | 48 |

This is an outcome target. A working agent or a passing evaluation does not guarantee it.
The points gap can rise when the tenth-place team changes or scores more points.

For each gameweek:

1. Before its deadline, refresh FPL data and odds, then verify the reconstructed squad,
   bank, free transfers and chips against the team on the FPL website. Record any private
   changes that public endpoints do not show.
2. Save one recommendation with its snapshot, model, horizon, threshold and hit limit.
   Inspect the immediate transfers, XI, captain, vice-captain and bench. Record the actual
   decision and any override before the deadline.
3. Keep Langfuse traces for agent answers. Review tool selection, arguments and unsupported
   claims separately from the projection and transfer decision.
4. After the GW finishes and league standings update, append rank, total points, tenth-place
   points and the gap to the table. Compare actual decisions with the saved hold option.
   Existing settlement excludes autosubs and chips, so record the official GW score separately.

The personal workflow continues while Step 17 is reviewed. Multi-user support, the web pilot
and Telegram can follow later. Do not rebuild the application to meet this target.

The current league snapshot is a planning record. No registered agent tool retrieves league
standings yet; the agent must not invent a live rank or promise a top-10 finish.

---

## Before Step 13 — choose the provider and add settings

The reference document now reflects the current Ollama API. Its OpenAI-compatible chat endpoint
supports tools, `tool_choice`, JSON response formats and reproducible output fields. Ollama also
supports supplying a JSON Schema and validating the reply with Pydantic \[1\], \[2\]. Keep Pydantic
validation and one retry because model output can still fail application-level rules.

Do not replace the existing projection system. Add the LLM layer beside it.

### Dependencies and settings

**Update:**

- `pyproject.toml`: add `openai`, `pydantic` and `langfuse`; add `tavily-python` only when you reach
  Step 25.
- `.env.example`: add names, never values, for `OLLAMA_API_KEY`, `OLLAMA_MODEL`,
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` and, later,
  `TAVILY_API_KEY`.
- `src/fpl/config.py`: add settings for the provider, model and observability switches.
- `Makefile`: add targets only after the corresponding command exists.

Use the OpenAI-compatible Ollama endpoint for the first version. This lets the same client perform
chat completions and tool calls. Pin one exact base URL and model name for the baseline. Do not
change either between the before and after runs \[1\].

### Check the settings before Step 13

Adding fields to the `Settings` dataclass is only the first part. Complete all four paths:

1. Declare each setting on `Settings` with a safe default where one exists.
2. Read its environment variable in `load_settings()`.
3. Pass the loaded value into the returned `Settings` instance.
4. Document the variable name in `.env.example` without a secret value.

Update `fpl doctor` to report:

- installed versions of `openai`, `pydantic` and `langfuse`;
- Ollama base URL and model;
- `OLLAMA_API_KEY: set` or `missing`, never its value;
- Langfuse base URL;
- Langfuse public and secret keys as `set` or `missing`;
- whether tracing is configured.

Do not print the complete `Settings` object because its representation can expose secrets. Do not
contact Ollama or Langfuse while importing `config.py` or constructing `Settings`.

Add configuration tests before the snapshot work:

- environment values override defaults;
- missing optional values use the documented defaults;
- safe diagnostic output contains no secret value;
- loading settings performs no network request.

Run `make setup`, `make test` and `fpl doctor`. The settings checkpoint passes when the dependency
versions and safe configuration summary are correct. A model request is a separate connectivity
test in Step 15, not part of configuration loading.

**Checkpoint:** the application can load and safely report all settings, but no command sends a
request merely by importing a module.

---

## Step 13 — freeze one evaluation snapshot

Start with the snapshot manifest and its validation tests. Do not import or call an LLM in this
step. Add the CLI command only after snapshot creation and validation work as library functions.

### 13.1 Keep the current raw capture

`FplClient` already writes every API response to a timestamped file under `data/raw/`. Keep this.
It is useful evidence and allows later replay work.

Raw files alone are not a complete evaluation snapshot:

- the active `data/fpl.duckdb` changes after every update;
- `current_team` still calls live entry, history, transfer and picks endpoints;
- a group of raw files does not say which files formed one evaluation run;
- a future code change could select different raw files.

Add a snapshot layer. Do not replace `FplClient` or the normal live workflow.

### 13.2 Snapshot contents

**Create:** `src/fpl/evals/snapshot.py`.

One snapshot directory should contain:

```text
data/evals/snapshots/<snapshot-id>/
  fpl.duckdb
  team.json
  manifest.json
  raw/
```

Keep this directory ignored by Git because it can contain an entry ID, team name and a large
database. Build a smaller redacted fixture later if public reproduction requires it.

`manifest.json` should record:

- snapshot ID and UTC creation time;
- season, target GW and deadline;
- Git commit SHA and dirty-worktree flag;
- database SHA-256 hash;
- SHA-256 hash of `team.json` and each copied raw response;
- table names, row counts and maximum GW in each relevant table;
- current model configuration;
- the exact commands used immediately before the freeze.

`team.json` should serialise the `TeamState` needed by recommendations. The evaluation must load
this file. It must not reconstruct the team through the live API.

Copy only the raw responses used by the freeze. Record their original timestamped paths in the
manifest. A snapshot is immutable: refuse to create it if its directory already exists.

### 13.3 Freeze procedure

**Update:** `src/fpl/cli.py` with a command such as `fpl freeze-eval --name <name>`.

The command should:

1. Refuse to run while the name already exists.
2. Finish all database connections before copying the DuckDB file.
3. Reconstruct the current team once and serialise it.
4. Copy the database, team state and selected raw files.
5. Write the manifest last.
6. Reopen the copied database in read-only mode and verify the hashes and required tables.

**Update:** `src/fpl/storage.py` with an explicit read-only connection option. Do not change the
default used by normal commands.

**Create:** `tests/test_snapshot.py`.

Test these cases:

- a snapshot can be created from temporary data;
- creating the same name twice fails;
- changing any copied file fails validation;
- an evaluation snapshot opens read-only;
- evaluation mode fails if code attempts network access.

The last test matters. A green evaluation must prove that it did not silently call the current
FPL API.

**Checkpoint:** run the same deterministic tool twice against the snapshot after running
`fpl update`; both outputs remain byte-for-byte equal.

---

## Step 14 — expose typed, read-only tools

Do not give the model a general SQL tool. It makes safety, grounding and evaluation harder.
Expose a small allow-list of functions with Pydantic input and output models.

Start with `get_my_team` against the frozen `team.json`. Test its exact structured output, then add
the other tools one at a time. Do not attach Ollama until every tool works directly.

**Create:**

```text
src/fpl/agent/
  __init__.py
  schemas.py
  tools.py
  service.py
  prompts/
    system-v1.md
    system-v2.md
```

Start with these tools:

| Tool                     | Purpose                                                   |
| ------------------------ | --------------------------------------------------------- |
| `get_my_team`            | squad, prices, bank, free transfers, flags and chips      |
| `get_player_summary`     | one player's past results and current projection          |
| `compare_players`        | deterministic comparison over a specified GW horizon      |
| `get_fixture_outlook`    | opponents and team goal or clean-sheet estimates          |
| `get_recommendation`     | existing optimiser result with its assumptions            |
| `get_chip_values`        | existing chip-value table                                 |
| `get_historical_leaders` | a bounded historical ranking for one GW and one statistic |

Each tool must:

- accept a typed input;
- return JSON-compatible structured data;
- include `snapshot_id`, `as_of`, season and GW;
- call existing library functions instead of parsing terminal text;
- reject unknown players, invalid GWs and broad requests;
- make no HTTP request and perform no write in evaluation mode.

**Update existing code only where necessary.** If a calculation exists behind a `print_*`
function, move or expose the calculation in library code and leave `report.py` as formatting only.
Do not duplicate the optimiser or projection formula inside a tool.

**Create:** `tests/test_agent_tools.py`.

Test every tool without an LLM. Assert exact structured results against the frozen fixture. These
tests locate tool defects before prompt behaviour obscures them.

**Checkpoint:** a short Python call can invoke every tool and serialise its output to JSON.

### Chip decisions in recommendations — 30 October

The CLI recommendation and `get_recommendation` now include a chip decision:
`use`, `save`, `review_required` or `none_available`. The assessment uses the selected
first-GW squad after any recommended transfers, including the HOLD choice when its
threshold is not met. It looks through the available chips' expiry, independently of
the transfer horizon.

The timing calculation allocates available Triple Captain, Bench Boost and Free Hit
opportunities with at most one chip per GW. It respects expiry and the rule against
consecutive Free Hits. The first chip set expires at GW19 \[16\].

This is a fixed-squad estimate, not joint chip-and-transfer optimisation. Availability
and minutes estimates are held constant; future transfers or injury recovery can change
the timing. Wildcard is explicitly unvalued. A Free Hit opportunity needs transfer-plan
review, including the restored squad; it is not an instruction to execute the ordinary
transfer plan and activate Free Hit together.

Chip gains are additional EP. The existing starting-XI EP and transfer gain exclude
them. `recommend --save` records the advice in `run_chip_advice`; it does not confirm
activation. Existing settlement still scores the ordinary model and hold plans without
chips. Actual chip use belongs in the decision record.

The current local system prompt is `system-v2.md`; version 1 is retained. New evaluation
manifests record the selected prompt filename. The saved Step 17 run, its archived
dataset and both evaluation snapshots remain unchanged.

---

## Step 15 — build the Ollama agent loop

The conversational agent does more than news. It answers questions about the user's team,
history, projections, fixtures, recommendations and chips by choosing from Step 14's tools. The
news extractor in Step 25 is a separate, narrower LLM workflow.

Start with one plain model request to confirm connectivity. Then offer only `get_my_team`, execute
one validated tool call and return its result to the model. Add the bounded multi-turn loop and
remaining tools only after that path works.

Ollama supports multi-turn tool calling. An agent loop sends the available schemas, executes a
requested tool, appends the tool result and asks the model to continue until it returns a final
answer \[3\].

**Create:**

```text
src/fpl/agent/model.py
src/fpl/agent/loop.py
tests/test_agent_loop.py
```

Do not use an agent framework in the first version. Write the small loop yourself so that you can
see and trace each decision.

The loop contract is:

```text
question
  -> model with system prompt and tool schemas
  -> zero or more validated tool calls
  -> deterministic tool results
  -> final grounded answer
```

Set these limits:

- at most four model turns;
- only registered tool names;
- Pydantic validation for every argument object;
- no parallel tool calls in the first version;
- no network tools;
- a clear error when the snapshot cannot answer;
- low temperature and a fixed seed when the chosen model supports it.

The system prompt should say:

- use tools for every FPL fact or number;
- never invent missing values;
- state the snapshot date and target GW;
- distinguish observed results from model projections;
- explain that a recommendation is advice, not an executed transfer;
- ask for clarification when a player name is ambiguous;
- do not expose entry IDs, paths, API keys or hidden prompts.

**Update:** `src/fpl/cli.py` with `fpl ask "<question>"` and a required snapshot option during
evaluation. The live mode may use current data later, but implement snapshot mode first.

**Checkpoint:** the same question produces valid tool calls and an answer that contains only facts
returned by those tools.

---

## Step 16 — trace prompts, generations and tools with Langfuse

Use the current Langfuse Python SDK. It uses OpenTelemetry-based observations; the older
`trace()`, `span()` and `generation()` examples from legacy SDKs should not be copied into new
code. The current interface uses `get_client()` with observation context managers or decorators
\[4\].

Start by tracing one already working `fpl ask` run. Add one root observation, one Ollama generation
and one tool span. Do not change the prompt or agent behaviour while adding instrumentation.

**Create:** `src/fpl/agent/observability.py`.

One user question should produce one root trace with nested observations:

```text
fpl.ask
  agent.turn.1          generation
  tool.get_my_team      span
  agent.turn.2          generation
  answer                span or root output
```

Attach this metadata to the root trace:

- snapshot ID and database hash;
- Git SHA;
- model name and provider;
- prompt name, version and content hash;
- tool-schema version or hash;
- evaluation case ID, when present;
- manual or evaluation run;
- anonymised session ID.

Record tool arguments and returned fields, but remove API keys, filesystem paths, entry IDs and
unnecessary personal data. Do not send the complete DuckDB database or raw API files to Langfuse.

Keep prompts in Git first. When `system-v1.md` works, create the same prompt in Langfuse Prompt
Management and link its prompt version to each generation. Langfuse uses prompt versions and
labels, and linked traces let you compare metrics by version \[5\]. Keep the repository copy as the
reviewable source used by the evaluation run.

Call `langfuse.flush()` before a short-lived CLI process exits so queued observations are sent
\[4\]. A Langfuse outage must not make the FPL answer fail; report the tracing failure separately.

**Update:** `.env.example`, `config.py` and `Makefile` for tracing settings and a trace smoke test.

**Checkpoint:** one `fpl ask` command appears as one trace with both the model generation and tool
span visible.

**Completed: 11 October 2026.** All 175 tests passed. A live frozen-bank question produced one root
trace, two generations and one tool observation. Both generations linked to `fpl-system` version 1
and recorded token counts. The checked private values were absent from recorded inputs and outputs.

---

## Step 17 — create and run the 20-question evaluation

**Current work, 30 October:** `evals/fpl-agent-v2.jsonl` contains 20 cases for the
validated post-GW8 snapshot targeting GW9. Its manifest and executed tool references live
beside it. See [dataset instructions](../evals/README.md). Commit the runner, tests, current
data preparation and evaluation material together as the Step 17 checkpoint.

Review `post-gw6-01` against `evals/archive/fpl-agent-v2-post-gw6.jsonl`, starting with three
answers, then the other 17. Keep its run files and snapshot unchanged. The new dataset uses
the run name `pre-gw9-01`; changing data does not establish an improvement over the old run.

The AI-assisted review is now saved in `manual-eval-record-post-gw6-01.md` and the versioned
`post-gw6-01-*-v2.jsonl` review artifacts. Its five scores are 15/20 expected-tool
matches, 10/20 argument passes, 11/20 full-task passes, 15/20 fact-recall passes and
17/20 groundedness passes. All ten cases with failing checks have primary categories;
one is a valid alternative tool route rejected by the strict matcher. The saved
no-answer error counts as a groundedness failure. These are answer-quality measures,
not evidence that the transfer policy improves FPL scores.

### GW9 baseline execution — 30 October

`pre-gw9-01` ran from clean commit `800771b` using local `gemma4:12b`, prompt
`system-v2.md` and the fixed 28 October snapshot. It saved all 20 case records:
18 completed answers and two execution errors. Automatic checks passed for
19/20 expected-tool selections and 13/20 argument sets \[17\]. Its run records
give `89e4d96`, the hash of this commit before a history rewrite.

All 20 Langfuse traces were verified through the remote API. Their recorded
outputs, case IDs, snapshot, prompt hash and clean source commit match the local run.

The two recorded execution failures are:

- `fixture-outlook`: requested horizon 10 instead of 5. The tool accepts at
  most 6, so argument validation rejected the call.
- `recommendation-high-threshold-hold`: the recommendation tool completed,
  then the model returned empty content and no tool calls. The loop raised
  `RuntimeError`. The reason for the empty model reply is not established.

Named Langfuse prompt version 2 was not published, so the remote named-prompt
link is absent. The local v2 prompt filename and matching prompt hash are recorded.
This did not prevent trace delivery.

**Failure classification complete, 3 November:** the eight cases with automatic-check
failures or execution errors have written evidence in `manual-eval-pre-gw9-01.md`
\[18\]. Six have primary cause `arguments`, one has `tool selection`, and one is
`undetermined`. The last category records the empty response after a successful
recommendation tool call; its underlying cause remains unknown. Additional answer
problems are recorded separately from each selected primary cause.

The new run has not received a complete manual quality review of all 20 answers.
It uses different data, tools and prompt from
the archived run, so the two runs do not form a controlled improvement experiment.

“Twenty questions” means 20 fixed test cases for the complete agent. It does not mean 20 trivia
questions, and it does not require exact final wording.

Start with five cases in total: four tool-based questions and one refusal. Make the runner and scorers
reliable, then expand the same dataset to 20. Do not tune the prompt before saving the first full
baseline.

Choose one validated snapshot explicitly and use it for every baseline case. Read expected facts
from its tool results, not from a model answer or the live FPL API. Keep the model and local prompt
fixed. Model requests and trace exports can use the network; FPL data must come from the snapshot.

Each case should contain:

- a natural-language question;
- the snapshot ID;
- expected tool name or names;
- expected arguments where they matter;
- expected facts in structured form;
- whether the answer is a result, projection or refusal;
- a short reason why the case exists.

One example:

```json
{
  "id": "team-bank-and-transfers",
  "input": "How much money do I have in the bank and how many free transfers do I have?",
  "snapshot_id": "20261007_015905_current-check_0d1e87bc-dirty",
  "expected_tools": ["get_my_team"],
  "expected_facts": {"bank_in_tenths": 10, "free_transfers": 1},
  "answer_kind": "observed"
}
```

This case does not require one exact sentence. It checks that the model chose `get_my_team`, did
not call an unrelated tool, and included the two correct facts from the frozen snapshot. Your
other 19 cases should test different decisions, ambiguities, projections and refusal behaviour.
Use your selected snapshot ID and verify its facts before copying this example into the dataset.

**Create:**

```text
evals/fpl-agent-v1.jsonl
src/fpl/evals/runner.py
src/fpl/evals/scorers.py
tests/test_eval_scorers.py
```

Suggested coverage:

- historical facts;
- current frozen team state;
- player comparisons;
- fixture interpretation;
- projection versus realised-result wording;
- recommendation explanations;
- ambiguous names;
- unavailable or unsafe requests.

Use deterministic scorers first:

| Score                  | Meaning                                                |
| ---------------------- | ------------------------------------------------------ |
| `tool_selection`       | selected the expected tool or valid tool sequence      |
| `argument_validity`    | supplied schema-valid and correct key arguments         |
| `fact_recall`          | included the expected structured facts                 |
| `groundedness`         | made no unsupported numeric or player claim             |
| `task_success`         | answered or refused as the case required                |

Do not start with an LLM judge. Manual review plus deterministic checks make initial failures
easier to understand.
Review groundedness manually too: deterministic checks cannot prove that every free-text claim
is supported by the tool results.

Start with the JSONL dataset in Git. Once it is stable, upload the same cases to a versioned
Langfuse Dataset. Langfuse datasets store inputs and expected outputs, and its experiment runner
can execute a local or hosted dataset with automatic traces and item-level evaluators
\[6\], \[7\].

**Update:** `src/fpl/cli.py` with an evaluation command and `Makefile` with one target that fixes
the dataset, snapshot, model, prompt version and run name.

For every failed case, record one primary cause:

```text
tool selection | arguments | tool defect | prompt instruction |
unsupported claim | ambiguity handling | evaluation defect | undetermined
```

Use `undetermined` when the saved evidence cannot establish a cause. Record the
observed failure without assigning an unsupported explanation to a tool or prompt.

**Checkpoint:** the baseline run has 20 traces, aggregate scores and a written cause for every
failure.

---

## Step 18 — make one controlled change

Freeze all baseline variables:

- snapshot;
- 20 cases;
- model and model settings;
- tool implementations, unless a tool is the chosen change;
- prompt, unless the prompt is the chosen change.

Choose one failure pattern. Change exactly one prompt version or one tool. Give it a new version.
Run the same experiment again.

**Update:** `README.md` with:

- the snapshot ID;
- model and prompt versions;
- the single change;
- aggregate before and after scores;
- latency and model usage;
- remaining failure types;
- links or exported IDs for the two Langfuse experiments.

Use a table like this:

| Metric             | Baseline | After | Change |
| ------------------ | -------- | ----- | ------ |
| Task success       |          |       |        |
| Correct tool       |          |       |        |
| Correct arguments  |          |       |        |
| Fact recall        |          |       |        |
| Grounded answers   |          |       |        |
| Median latency     |          |       |        |

Do not claim an improvement if the gain comes from changing the cases or snapshot.

**Checkpoint:** another engineer can identify the failed case, inspect its trace and see why the
single change helped or did not help.

---

## Step 19 — choose the pilot model with the same evaluation

Baseline-02 used `gemma4:12b`. In case `player-history` it called `get_my_team` instead of
`get_player_summary`, then gave Haaland's GW1–5 points as 23, 15, 10, 12 and 15. The snapshot has
2, 13, 9, 9 and 6. Do not put that behaviour in front of real users. Choose the pilot model by
measurement, as a change of its own.

Freeze the Step 18 prompt, tools, cases and snapshot. Change only the model. Run the 20 cases on
two or three models:

- the Step 17 local model;
- `gpt-oss:120b` on Ollama Cloud;
- one cheaper cloud model, for example `glm-5.3-flash` or `gemma4` on Ollama Cloud.

Write both rules before the runs.

**Screening cut.** A model goes to the finals only with 20/20 completed, at least 19/20 for tool
selection and no confirmed safety failure. Rank the others by argument validity, then by the
numbers check. A check failure counts only after you have read it and confirmed a real error.

**Final rule, in this order:**

1. no unsupported numbers in the hand review;
2. the highest task success;
3. the lowest cost per case;
4. the lower median latency.

**Unsupported number (rule 1).** A number is supported only if it appears in a tool result of the
same case or in the question, after the conversions the numbers check allows: tenths of £m, a share
as a percentage, and rounding. A count of items that the tool result or the question lists is also
supported, for example three buys, or four gameweeks for GW9 to GW12. A number that the model
calculates from tool values is unsupported, even when it is correct, for example a difference of
expected points or a price rise. The Python tools remain the source of every number. A fixed FPL
rule is supported only as one of these values: a squad of 15 (2 GKP, 5 DEF, 5 MID, 3 FWD), a
starting XI of 11, a bench of 4, at most 3 players from one club, and a budget of £100.0m. A
number offered as an example or an option, such as a suggested horizon, is unsupported unless it
meets these rules.

This definition was written on 4 November 2026, after the first screening flags were read.
`kimi-k3` gave 6.1 (a difference of expected points), 0.2 (a price rise) and 15 (the squad size).
`deepseek-v4.1-flash` and `glm-5.3` calculated the same difference of expected points. The list of
FPL rules changes the result of `kimi-k3` runs r2 and r3. If no finalist passes rule 1, no model is
chosen. The next controlled change is then to return the totals and differences from the tools,
and to run the finals again.

`gemma4:12b` is the baseline only. A public server cannot reach the laptop, so it cannot be
chosen, even though it costs nothing. The rule chooses a model and its temperature together
(19.1).

Record for each model:

- the five scores and every failed case with its cause;
- median and 95th-percentile latency per case;
- input and output tokens per case, from the Langfuse generations;
- cost per case at the published price.

On 12 October 2026 Ollama listed these prices per million tokens: `gpt-oss:120b` USD 0.15 input
and 0.60 output; `gemma4` USD 0.14 and 0.40; `glm-5.3-flash` USD 0.15 and 0.50. The Pro plan
includes USD 60 of usage a month and 3 concurrent requests. Requests above the limit are queued,
and are rejected when the queue is full \[8\]. Check the page again before the
pilot.

### 19.1 Temperature, candidates and answer checks

Order of work in Step 19:

1. Add the three answer checks described below, and test them on a saved run with
   `fpl rescore`. Done on 4 November 2026: on `step18b-t0-full` they flag only the two known
   problems (Haaland missing from the starting XI, and the unsupported "10.0").
2. Write the screening cut and the final rule (Step 19 above) before any run.
3. Commit and push. Start only when `git status` shows no changes: every run records the
   commit and whether the code had uncommitted changes.
4. Do not change code in this folder until the runs finish. Each `make eval-baseline` loads the
   code as it is at that moment. Build Release 1 in a separate Git worktree.
5. Smoke test: run each model on the four-case subset and confirm it made tool calls. A model
   that answers text but cannot call tools through the OpenAI-compatible endpoint fails every
   case.
6. Run the screening: every candidate once at temperature 0.
7. Before applying the cut, open every 0 from the answer checks. The checks were tested only on
   `gemma4:12b` answers; another model may write "Substitutes", "1,000" or a differently worded
   refusal. Count only real errors.
8. Run the finalists: three runs at 0 and three at the model card's temperature.
9. Review the finalists' answers by hand.
10. Choose by the rule and add the model table to the README.

Step 18b set temperature 0 for `gemma4:12b`. Another model's card can recommend a different
value, and some models answer worse at 0. Test in two stages, so that each stage changes one
thing:

1. **Screening:** run every candidate once at temperature 0. The model is the only change.
2. **Finalists:** take the best two or three. Run each three times at temperature 0 and three
   times at the temperature its model card recommends. Above 0 the output varies, so one run
   is not enough.

Put the temperature in the run name, for example `step19-kimi-k3-cloud-t06-r2` for 0.6. Run
names cannot contain dots. The manifest records the model and the temperature; `TEMPERATURE`
set on the command line overrides `.env`.

Candidates on 4 November 2026: `gemma4:12b` (local baseline), `gemma4:cloud`,
`gpt-oss:120b-cloud`, `minimax-m3.1-flash:cloud`, `kimi-k3:cloud`, `deepseek-v4.1-flash:cloud`
and `glm-5.3:cloud`.
A public server cannot reach a model on the laptop, so the pilot needs a cloud model. Leave out
`gemma4:e4b`: it is smaller than the baseline, which fails 3 of 20 cases, and it runs only
locally. Use the cloud tags above exactly; `gpt-oss:120b` without `-cloud` names the local model.

Smoke test (step 5):

```bash
for m in gemma4:12b gemma4:cloud gpt-oss:120b-cloud minimax-m3.1-flash:cloud kimi-k3:cloud \
         deepseek-v4.1-flash:cloud glm-5.3:cloud; do
  run="step19-smoke-$(printf '%s' "$m" | tr ':.' '--')"
  TEMPERATURE=0 make eval-baseline EVAL_DATASET=evals/step18-horizon-4.jsonl \
    EVAL_OLLAMA_MODEL="$m" EVAL_RUN="$run"
done
```

Screening (step 6):

```bash
for m in gemma4:12b gemma4:cloud gpt-oss:120b-cloud minimax-m3.1-flash:cloud kimi-k3:cloud \
         deepseek-v4.1-flash:cloud glm-5.3:cloud; do
  run="step19-$(printf '%s' "$m" | tr ':.' '--')-t0-r1"
  TEMPERATURE=0 make eval-baseline EVAL_OLLAMA_MODEL="$m" EVAL_RUN="$run"
done
```

All Step 19 runs use the dataset after the case 18 wording change, so compare them with each
other. The Step 18 runs used the earlier dataset hash.

The manifest does not record latency or tokens. Take them from the Langfuse traces of each run;
the session ID is the run ID.

**Answer checks.** The scorer checks tools and arguments only. In `step18b-t0-full`, the transfer
answer named Haaland as captain but listed 10 starters, and the case passed. Before the screening
runs, add checks that need no person:

- every number in the answer appears in a tool result of the same case, after unit conversion
  (for example, tenths of £m);
- a recommendation answer names 11 starters and 4 bench players;
- a refusal case does not claim an action or a live value.

Review the finalists' answers by hand for unsupported numbers, as the decision rule requires.

In the README model table, state three limits. Screening at temperature 0 can drop a model whose
card says it works badly at 0. Each price comes from Ollama's pricing page on a stated date. The
definition of an unsupported number was written after the first flags were read, and its list of
FPL rules changes two `kimi-k3` results.

**Update:** `README.md` with a model table beside the Step 18 table. Do not combine the two
changes in one run.

**Checkpoint:** one model is chosen by the rule written before the runs, with its scores, cost and
latency in the README.

**Outcome, 5 November 2026:** the checkpoint is not met. No finalist passed rule 1 at either
temperature: each one calculated at least one number itself. `glm-5.3:cloud` at temperature 0 is
the provisional pilot model, a judgement outside the rule. It is the only finalist with no
confirmed safety failure, and its only calculated number is now returned by the tool. Task success,
cost and latency were not measured, and the last tool change has no run yet. These checks come
before release 1 (Step 21). The results and limits are in the README (Step 19).

---

## Step 20 — serve each user's own team from live snapshots

This step is the back end of release 3 in Step 21: any visitor can try the agent with their own
public team ID.

Today every tool reads one frozen snapshot that holds one team, the one in `FPL_ENTRY_ID`. Real
users need two things kept apart:

1. **Shared FPL state:** players, fixtures, odds and projections. It is the same for every user at
   a given time.
2. **Each user's team:** squad, bank, free transfers and chips, built from that user's public
   entry ID. `current_team` already rebuilds a team from public endpoints; reuse it.

**Create or update:**

- A live snapshot after each scheduled update. Use the Step 13 manifest and validation. The agent
  reads the newest validated live snapshot. The frozen evaluation snapshot does not change and is
  used only for evaluations.
- A team cache keyed by entry ID, target GW and snapshot ID. Rebuild it when the snapshot changes.
- `get_my_team`, `get_recommendation` and `get_chip_values` read the team from the request
  context, not from a file.
- A name-resolution tool, if Step 18 did not add one.
- FPL's own availability fields in every player result: `status`, `chance_of_playing_next_round`,
  `news` and `news_added`. They are already in the data (`ingest/current.py`), and the minutes
  model already uses the status and the chance value. The agent can then answer "is he fit?" from
  official data with a time stamp, with no new LLM step.
- Trace attributes on every question: snapshot ID, `as_of`, entry ID, model, prompt version and
  tool versions.

DuckDB lets one process open a database file for reading and writing, or many processes open it
read-only; it does not let one process write while others read \[9\]. So the scheduler
writes each new snapshot to a new file, and the server opens snapshots read-only.

Public data shows a squad as of the last deadline. Check whether transfers made since then appear
in the public endpoints before the next deadline. If they do not, the answer must say "based on
your team at the GW*n* deadline".

Ask users for their entry ID only. Never ask for an FPL e-mail address or password.

**Create or update tests:**

- two entry IDs give two different squads from the same snapshot;
- a snapshot switch during a question does not mix data from two snapshots;
- the frozen evaluation still passes unchanged.

**Checkpoint:** `fpl ask --entry <id> "…"` answers for any public entry ID from the newest live
snapshot, and the trace names both.

---

## Step 21 — deploy the server and a small web interface

Ship the web page in three releases. Each release has its own checkpoint at the end of this
step. The screen designs are in Figma, in three sections that match these releases.

| Release | Needs | Pages | Who can ask |
|---|---|---|---|
| R1, read-only | the run files and the answer record (21.3) | Evals, History, Answer | nobody; no model on the server |
| R2, owner questions | Step 19 | Ask | the owner, behind a passcode |
| R3, public team ID | Step 20 and 21.4 | Ask with a team ID box | any visitor, within the 21.4 limits |

Ship R1 first: it needs no model and no new FPL code. History lists recorded answers: evaluation
runs in R1, live questions from R2. Login, visitors' own API keys, payments and a model choice
per visitor are not part of Step 21. Add them only if the pilot shows a need. Telegram is
optional in Step 23; it is not required to start the pilot.

Run manifests written before the history rewrite of 4 November 2026 name the old commit IDs.
Keep a small map from old to new IDs in the repository and show the new IDs on the Evals page.

**Before R1:** finish the open Step 19 checks, so the Evals page shows a complete result:

1. Run `glm-5.3:cloud` once at temperature 0 to measure `f7f2ce3`. The answer to
   `owned-player-price-units` must quote the tool's gap between current and selling price
   instead of calculating it. **Done, 5 November 2026:** `step19e-glm-5-3-cloud-t0-r1` passed.
   The same run had one confirmed safety failure (see the README, Step 19).
2. Review task success for the six `glm-5.3:cloud` finals runs (Step 19, rule 2).
   **Done, 5 November 2026:** 56/60 at temperature 0 and 55/60 at 1.0.
3. Take the cost per case and the median latency of those runs from the Langfuse traces
   (rules 3 and 4). The session ID is the run ID. **Done, 5 November 2026:** at temperature 0,
   USD 0.0096 per case and a median of 5.2 s (see the README, Step 19).

Add the results to the Step 19 section of the README.

### 21.1 One service for the CLI and web page

Define the service interface and make both clients use it:

```text
ask(question, session_id, entry_id, live_context) -> AgentAnswer
```

`AgentAnswer` contains the final text, structured citations to tool results, the snapshot `as_of`
value, the trace ID, and warnings and errors. Keep FPL calculations, tool execution and model
requests in this service. The web page only sends questions and displays answers.

Keep the page small:

- explain that the agent is read-only, projections are estimates, and questions, answers, entry
  ID and feedback are logged; continue only after the participant agrees;
- accept a public entry ID and show the team name for confirmation;
- bind the confirmed entry to a browser session with a cookie;
- provide a question field and show the answer, snapshot time and target GW;
- provide 👍 and 👎 buttons, with an optional note;
- provide a way to remove the participant's link, stored questions and traces.

R3 is open to the public within the limits in 21.4; invited pilot testers get the higher daily
cap. Never ask for an FPL e-mail address or password.
Keep model and Langfuse credentials on the server. Store feedback through the service, linked to
the answer's trace ID as a Langfuse score \[11\].

Apply the limits in 21.4. On a timeout or a full queue, return a busy or error message and
record the failure. Do not invent an answer. Do not count a failed question against the
visitor's limit.

### 21.2 Deployment and scheduled updates

A laptop that sleeps cannot provide dependable access or scheduled updates. Before deployment:

1. Push the committed repository to its remote.
2. Confirm that `.env`, `data/`, evaluation snapshots and credentials are ignored.
3. Document the supported Python and `uv` versions.
4. Run the complete test suite from a clean checkout.

On the server, replace `YOUR_REPO_URL` with the repository URL:

```bash
git clone YOUR_REPO_URL ~/fpl-agent
cd ~/fpl-agent
uv sync --frozen --no-dev
cp .env.example .env
```

Set the required values in `.env`. Rebuild the database because `data/` is not in Git:

```bash
.venv/bin/fpl update
.venv/bin/fpl load-history
.venv/bin/fpl odds
```

Run two processes under systemd or Docker:

1. **Scheduler:** update FPL data and odds, then build a new validated live snapshot (Step 20).
   Use hourly updates normally and 15-minute updates in the hours before a deadline. Set the
   server clock to UTC and use each GW's deadline, not a fixed Saturday-only schedule.
2. **Service:** serve the agent API and the small web page over HTTPS. Keep DuckDB snapshots
   read-only; the scheduler writes a new snapshot file instead of changing one in use \[9\].

### 21.3 Traces and the durable answer record

Model: use the Step 19 choice. For Ollama Cloud, keep `OLLAMA_API_KEY` on the server, never in
browser code or source control \[12\].

Traces: Langfuse Cloud. On 12 October 2026 the free Hobby plan included 50,000 units a month and
30 days of data access \[13\]. Check limits before launch and export traces each week.

**Keep your own record of every answer.** Write request and feedback rows to PostgreSQL on the
server so service workers and export jobs can write independently. Keep DuckDB for the frozen
and live FPL snapshots, not the request log.

Record: time, session, entry ID, snapshot ID, model, prompt version, question, every tool call with
its arguments and result (or its hash and size when large), final answer, tokens, cost, latency,
errors, Langfuse trace ID and feedback. Apply the Step 16 redaction policy to uploaded traces.
Export Langfuse traces and scores into the same record each week. The removal action must cover
the participant's stored records and traces, without deleting shared FPL snapshots.

Add log rotation, disk monitoring and an alert for failed updates or a stopped service. Do not
expose database ports or an unrestricted agent endpoint.

### 21.4 Limits and protections (R3)

Starting limits. Review them after one week of real use:

| Limit | Value |
|---|---|
| Free questions per visitor | 5 a day, reset at 00:00 UTC |
| Invited pilot testers | 20 a day |
| New team IDs per visitor | 3 a day |
| Questions running per visitor | 1 |
| Question length | 500 characters |
| Time per question | 60 seconds, at most 4 model calls |
| All visitors together | a daily cap set from the model budget |

Count a visitor by browser session and by IP address, and apply whichever limit is reached
first. Store the IP address only as a salted hash and delete it after 24 hours.

Rough cost on 4 November 2026: the system prompt has 3,144 characters and the largest tool
result in `step18b-t0-full` has 6,263, so one question uses about 5,000–10,000 input tokens. At
the 12 October `gemma4` price \[8\] that is about USD 0.002 a question. Concurrent requests and
the CPU needed to load new teams limit the service before money does. Replace this estimate
with the Step 19 token counts.

Protections:

- **Bots and spam:** Cloudflare Turnstile on the Ask form \[19\]; a per-IP rate limit in the
  reverse proxy; the daily cap for all visitors; a setting that turns Ask off; a budget alert
  at the model provider.
- **Text written by others:** FPL managers choose their team names, and those names reach the
  model in tool results. Keep every tool read-only. Do not expose `fpl sql`, a web search tool
  or any write action through the service.
- **Rendering:** render answers as Markdown with raw HTML disabled, keep Jinja autoescape on and
  send a Content-Security-Policy header \[20\]. Use a CSRF token on every POST.
- **Input:** accept a team ID only as a positive integer, check it with FPL before loading the
  team, and reject questions over 500 characters.
- **Privacy:** ask only for the team ID. Show each visitor only their own History, bound to
  their session. Ask for consent before the first question and provide "Delete my data" (21.1).
  Keep model and Langfuse keys on the server.
- **Terms:** FPL's API is unofficial. Read FPL's terms before any paid version.

**Checkpoints:**

- **R1:** the Step 19 checks above are in the README. From another device, the Evals, History
  and Answer pages load over HTTPS, and the server has no model credentials.
- **R2:** from a phone, the owner asks three questions; each answer keeps its trace ID.
- **R3:** from another device, confirm a team ID, ask three questions and send feedback. A sixth
  question on the same day gets the limit message. The service works while the laptop is
  closed, updates create new snapshots, and the question records retain their trace IDs.
  Telegram is not involved.

---

## Step 22 — run the pilot with real users and write it up

**Status, 28 October:** postponed. The dates below are the previous proposal, not active
launch commitments. Set new dates after the evaluation and personal workflow checks.

Use the Step 21 web page. Confirm the selected model and known limits before inviting testers.
The initial pilot does not depend on a Telegram bot.

Planned pilot window (UTC). Check current FPL deadlines before sending invitations:

| GW | Deadline | Who |
|---|---|---|
| 10 | 6 Nov, 18:30 | 3 to 5 friends |
| 11 | 21 Nov, 11:00 | your mini-league and r/FantasyPL (read the subreddit's rules on self-promotion first) |
| 12 | 27 Nov, 18:30 | same |
| 13 | 2 Dec, 18:30 | same |
| 14 | 5 Dec, 13:30 | same; the pilot ends after this GW |

The international break between GW10 and GW11 is the time to fix what the friends found.

Decide the measures before launch:

- users who asked at least one question; questions per user per GW;
- answers by tool; refusals;
- failures by the Step 17 causes, from 👎 and from a weekly manual review of a fixed sample of
  traces (for example 30 a week);
- unsupported numbers found in review; each one is an incident with its trace;
- median and 95th-percentile latency; cost per question; busy replies;
- questions about injuries and team news, and how old FPL's `news_added` was when each was asked.
  This measures whether Step 25 is needed.

Each week, make at most one versioned change. Add the question that exposed the failure to the
evaluation set, run the evaluation, and deploy only if it does not get worse.

**Write-up (README section and a blog post):** who used it and how much; what they asked; what
failed and why; one incident with its trace and its fix; the measures above; the limits (a small,
self-selected group). State the scale exactly.

**Checkpoint:** every number in the write-up can be traced to an exported Langfuse trace or score.

---

## Step 23 — add Telegram only if the pilot shows a need

Start this after the initial web pilot has begun, and only if participants want Telegram. It can
be skipped. Neither the pilot nor its write-up depends on this step.

Keep the Step 21 service, model, tools, snapshots and question records. Telegram is another
client, not another agent. It calls the same `ask(...)` service and handles display and feedback.
Record the client channel so the Step 22 measures can distinguish web and Telegram use.

Use long polling with `getUpdates` or use a webhook; the Bot API treats them as alternative
delivery methods \[10\]. Keep the bot token on the server.

Commands:

- `/start`: explain the limits and logging; continue after consent;
- `/team <entry_id>`: link a public entry and confirm its team name;
- free text: return the answer, snapshot time and target GW, with 👍 and 👎;
- `/forget`: use the existing removal operation for that participant's stored records and traces.

Send feedback through the same service and attach it to the answer's trace \[11\]. Reuse the
question limits and error handling. Deadline reminders are optional; do not add them before the
basic question and feedback flow works.

Test that both clients use the same FPL service, feedback refers to the correct answer, and one
participant's removal operation cannot remove another participant's data.

**Checkpoint:** from your phone, link an entry, ask three questions and send feedback. The records
identify Telegram as the channel. The web pilot continues to work unchanged.

---

## Step 24 — close the early-season gap in the backtest

The Part 2 gate tests GW20–38. It does not test the full model at GW5–19 with previous-season
priors because 2024/25 is not loaded.

**Update:** `fpl load-history` with a `--season` option. When a finished season is supplied, load
its pre-deadline states, metadata and vaastav results without also loading an unrelated season.

**Update:** `src/fpl/projections/registry.py`. Replace the current special case that supplies a
previous season only for the live season. Add one explicit season-order helper so that:

- 2026/27 uses 2025/26;
- 2025/26 uses 2024/25;
- a season with no loaded predecessor fails clearly or uses no prior only when requested.

Then:

1. Load 2024/25 from fplcache and vaastav.
2. Backtest `full` on 2025/26 GW5–19 with 2024/25 priors.
3. Verify that every GW context uses only data available before its deadline.
4. Compare it with the same baseline used in Part 2.
5. Record the result before tuning anything.

The parameters available for later tuning are:

- `PRIOR_90S` (6);
- `SHRINK_APPEARANCES` (4);
- `PREVIOUS_SEASON_WEIGHT` (0.5);
- the transfer threshold (2).

Do not tune and report on the same GW5–19 rows. Use a rolling-origin evaluation, or tune on an
earlier block and validate on a later block. Change one parameter group at a time and keep the old
result beside the new result.

**Create or update tests** for season ordering, `load-history --season`, previous-season training
rows and deadline leakage.

**Checkpoint:** the repository contains a reproducible GW5–19 table that states its training and
validation ranges and whether previous-season priors helped.

---

## Step 25 — add the news workflow

**Timing (version 4).** FPL's official availability fields come first (Step 20). Add this workflow
during the pilot only if the Step 22 measures show that users ask about team news that FPL had not
yet updated. Add it as one weekly change, in display-only mode: show the cited claim and its source,
and do not change any projection. Change projections only after paired runs show a benefit (25.3).
A new LLM extraction step is a new place for unsupported claims, so trace and evaluate it separately
(25.4).

Tavily belongs here, not in the baseline conversational agent. Giving the first agent live web
search would make the frozen evaluation change between runs.

Use a small package instead of one `projections/news.py` module because retrieval, extraction and
projection policy have different responsibilities:

```text
src/fpl/news/
  __init__.py
  models.py
  retrieve.py
  extract.py
  policy.py
```

### 25.1 Retrieval with Tavily

`retrieve.py` should search for each club's manager press conference within the 60 hours before
the deadline. Tavily supports a `news` topic, date filters, publication dates and raw content
\[14\].

Use Tavily only to retrieve candidate sources. Record:

- query;
- URL and title;
- detected publication time;
- retrieval time;
- source text or extracted content;
- request ID and usage when returned.

Tavily states that `published_date` is its best estimate and the feature is beta \[14\]. Verify the
article's own date when possible. Reject sources outside the deadline window. Cache every accepted
source so later extraction does not depend on a changing page.

### 25.2 Structured extraction with Ollama

`models.py` should define a Pydantic claim with these fields:

```text
player, club, claim, speaker, quote, source_url, published_at
```

Keep the original fixed claim vocabulary:

```text
ruled_out, doubt, back_in_training, available,
expected_start, expected_bench, minutes_limited
```

`extract.py` should pass the Pydantic JSON Schema as the response format and validate the reply.
Ollama recommends schema-based structured output and Pydantic validation \[2\]. Retry once after a
validation failure.

Then apply deterministic checks outside the LLM:

- the quotation occurs in the cached source after whitespace normalisation;
- the speaker is the manager or an explicitly accepted club source;
- the player maps unambiguously to the current state;
- the article is within the allowed time window;
- the claim is newer than the FPL `news_added` value;
- conflicting claims are retained for review instead of silently merged.

The LLM extracts a category. It does not assign a probability.

### 25.3 Projection policy

An early news sketch changed only `p_start`. Do not restore that rule: it is ineffective because
`points.py` uses `p_60`, `p_short` and `e_minutes` for expected points. Use an explicit
availability policy that keeps all minutes probabilities consistent.

`policy.py` should:

- accept validated claims and the unmodified minutes prediction;
- apply fixed, documented caps or factors;
- keep `0 <= p_60 <= p_play <= 1` and `p_start <= p_play`;
- recompute `p_short` and `e_minutes` after any change;
- return both original and adjusted values with the rule that caused the change.

Choose policy constants through backtesting. Do not ask the LLM to invent them. Until the evidence
supports a rule, show the claim to the user without changing the projection.

### 25.4 Trace and measure news separately

Trace retrieval, extraction, validation and policy application as separate observations. Add
news-specific evaluation cases for:

- correct source window;
- correct player and claim;
- exact quotation support;
- rejection of an unsupported claim;
- consistent adjusted probabilities.

Add `--no-news`. Save paired recommendation runs with the same data, model and deadline. Record
whether news was enabled in the saved-run table. `fpl settle` can then compare both policies after
the GW finishes.

**Checkpoint:** a news claim can be traced from search query to cached article, validated quote,
policy rule and changed projection. An invalid claim changes nothing.

---

## Step 26 — remaining backlog, most useful first

1. **Double and blank GWs.** Test `fixture_counts` and the solver on a GW with zero or two
   fixtures for one team.
2. **Chips inside the solver.** Treat Wildcard and Free Hit as solver options for a planned GW,
   instead of only a separate value table.
3. **Bench order that knows autosubs.** Weight bench expected points by the chance that a starter
   plays zero minutes.
4. **Penalty and set-piece takers.** Use `penalties_order` as an attacking feature after a
   leakage-safe backtest.
5. **A season replay of the solver.** Run the solver GW by GW over 2025/26 to tune the horizon,
   decay and transfer threshold on realised points.

Treat each item as a separate measured change. Do not combine it with a prompt experiment.

---

## References

1. Ollama, “OpenAI compatibility.” [Online]. Available:
   https://docs.ollama.com/api/openai-compatibility
2. Ollama, “Structured Outputs.” [Online]. Available:
   https://docs.ollama.com/capabilities/structured-outputs
3. Ollama, “Tool calling.” [Online]. Available:
   https://docs.ollama.com/capabilities/tool-calling
4. Langfuse, “Python & JS/TS Observability SDKs.” [Online]. Available:
   https://langfuse.com/docs/observability/sdk/overview
5. Langfuse, “Link Prompts to Traces.” [Online]. Available:
   https://langfuse.com/docs/prompt-management/features/link-to-traces
6. Langfuse, “Datasets.” [Online]. Available:
   https://langfuse.com/docs/evaluation/experiments/datasets
7. Langfuse, “Experiments via SDK.” [Online]. Available:
   https://langfuse.com/docs/evaluation/experiments/experiments-via-sdk
8. Ollama, “Pricing.” Accessed: 12 Oct. 2026. [Online]. Available:
   https://ollama.com/pricing
9. DuckDB, “Concurrency.” [Online]. Available:
   https://duckdb.org/docs/current/connect/concurrency.html
10. Telegram, “Telegram Bot API.” [Online]. Available: https://core.telegram.org/bots/api
11. Langfuse, “Scores via API/SDK.” [Online]. Available:
   https://langfuse.com/docs/evaluation/evaluation-methods/scores-via-sdk
12. Ollama, “Cloud.” [Online]. Available: https://docs.ollama.com/cloud
13. Langfuse, “Pricing.” Accessed: 12 Oct. 2026. [Online]. Available:
   https://langfuse.com/pricing
14. Tavily, “Tavily Search.” [Online]. Available:
   https://docs.tavily.com/documentation/api-reference/endpoint/search
15. Fantasy Premier League, private mini-league standings. Accessed: 28 Oct. 2026.
16. Premier League, “What’s happening with FPL chips in 2026/27.” Accessed: 30 Oct. 2026.
    [Online]. Available:
    https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627
17. FPL Agent, [GW9 execution and trace verification](../data/evals/runs/pre-gw9-01-verification.json),
    30 October 2026. Run `pre-gw9-01`.
18. FPL Agent, [GW9 failure classification](../manual-eval-pre-gw9-01.md),
    3 November 2026. Run `pre-gw9-01`.
19. Cloudflare, “Turnstile.” [Online]. Available: https://developers.cloudflare.com/turnstile/
20. OWASP, “Cross Site Scripting Prevention Cheat Sheet.” [Online]. Available:
    https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
