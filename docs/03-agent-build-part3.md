# FPL Agent — Build, Part 3: frozen data, an LLM layer, traces and evals

Version 2, 1 October 2026. This guide starts at Step 13, immediately after Part 2. It adds a
read-only conversational agent around the existing FPL calculations. It then adds tracing, a
fixed evaluation set, the early-season backtest, the news extractor and the remaining deployment
work.

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
| 19   | the early-season backtest                 | a GW5–19 test with previous-season priors             |
| 20   | the Tavily and Ollama news workflow       | cited manager claims that can affect minutes safely  |
| 21   | optional server deployment                | scheduled snapshots continue while the laptop sleeps |
| 22   | a stable service boundary for a later UI  | CLI and UI can use the same agent implementation     |
| 23   | the remaining model backlog               | ordered work after the measured agent changes        |

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
  Step 20.
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

---

## Step 15 — build the Ollama agent loop

The conversational agent does more than news. It answers questions about the user's team,
history, projections, fixtures, recommendations and chips by choosing from Step 14's tools. The
news extractor in Step 20 is a separate, narrower LLM workflow.

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
- live or evaluation mode;
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

---

## Step 17 — create and run the 20-question evaluation

“Twenty questions” means 20 fixed test cases for the complete agent. It does not mean 20 trivia
questions, and it does not require exact final wording.

Start with five cases that exercise different tools and one refusal. Make the runner and scorers
reliable, then expand the same dataset to 20. Do not tune the prompt before saving the first full
baseline.

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
  "snapshot_id": "pre-gw6-2026-09-30",
  "expected_tools": ["get_my_team"],
  "expected_facts": {"bank_tenths": 10, "free_transfers": 1},
  "answer_kind": "observed"
}
```

This case does not require one exact sentence. It checks that the model chose `get_my_team`, did
not call an unrelated tool, and included the two correct facts from the frozen snapshot. Your
other 19 cases should test different decisions, ambiguities, projections and refusal behaviour.

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

Start with the JSONL dataset in Git. Once it is stable, upload the same cases to a versioned
Langfuse Dataset. Langfuse datasets store inputs and expected outputs, and its experiment runner
can execute a local or hosted dataset with automatic traces and item-level evaluators
\[6\], \[7\].

**Update:** `src/fpl/cli.py` with an evaluation command and `Makefile` with one target that fixes
the dataset, snapshot, model, prompt version and run name.

For every failed case, record one primary cause:

```text
tool selection | arguments | tool defect | prompt instruction |
unsupported claim | ambiguity handling | evaluation defect
```

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

## Step 19 — close the early-season gap in the backtest

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

## Step 20 — add the news workflow

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

### 20.1 Retrieval with Tavily

`retrieve.py` should search for each club's manager press conference within the 60 hours before
the deadline. Tavily supports a `news` topic, date filters, publication dates and raw content
\[8\].

Use Tavily only to retrieve candidate sources. Record:

- query;
- URL and title;
- detected publication time;
- retrieval time;
- source text or extracted content;
- request ID and usage when returned.

Tavily states that `published_date` is its best estimate and the feature is beta \[8\]. Verify the
article's own date when possible. Reject sources outside the deadline window. Cache every accepted
source so later extraction does not depend on a changing page.

### 20.2 Structured extraction with Ollama

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

### 20.3 Projection policy

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

### 20.4 Trace and measure news separately

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

## Step 21 — deploy a server only when scheduled capture matters

A laptop that sleeps misses hourly data. This does not affect the frozen evaluation, but it can
leave gaps in later live snapshots. Use a small VPS only when those gaps matter.

Before deployment:

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

Schedule commands with cron or a systemd timer. Start with the original capture policy:

```cron
17 *    * * *  cd ~/fpl-agent && .venv/bin/fpl update >> data/update.log 2>&1
*/15 6-9 * * 6 cd ~/fpl-agent && .venv/bin/fpl update >> data/update.log 2>&1
```

Set the server clock to UTC. Adjust the second schedule when the deadline day or time changes.
Add log rotation, disk monitoring and a failure alert before relying on the server unattended.

Do not expose the DuckDB file or agent endpoint publicly without authentication. Keep Ollama,
Tavily and Langfuse secrets on the server.

**Checkpoint:** a scheduled update succeeds from a clean server, writes a timestamped raw response
and reports a failed run without exposing a secret.

---

## Step 22 — keep the later UI thin

Do not build the UI before the CLI agent and evaluation are stable.

Define one application service interface now:

```text
ask(question, session_id, snapshot_or_live_context) -> AgentAnswer
```

`AgentAnswer` should contain:

- final text;
- structured citations to tool results or news sources;
- snapshot or live `as_of` value;
- trace ID;
- warnings and errors;
- optional structured cards for team, player, fixture or recommendation output.

The CLI calls this service first. A later web UI calls the same service. The UI may render cards,
history and feedback, but it must not open DuckDB directly, calculate projections or execute
tools itself.

Keep API keys on the server. Ollama's cloud documentation explicitly says not to put the API key
in browser code or source control \[9\].

---

## Step 23 — remaining backlog, most useful first

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
8. Tavily, “Tavily Search.” [Online]. Available:
   https://docs.tavily.com/documentation/api-reference/endpoint/search
9. Ollama, “Cloud.” [Online]. Available: https://docs.ollama.com/cloud
