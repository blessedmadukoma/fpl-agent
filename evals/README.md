# FPL agent evaluation data

The active dataset contains 20 fixed cases for the post-GW8 snapshot created
on 28 October 2026. Its target is GW9; historical answers use completed GWs
and projections cover GW9 onwards. Question and reference preparation was
delegated to AI. Manual answer review remains learner work.

| File | Purpose |
| --- | --- |
| `fpl-agent-v2.jsonl` | Current 20 questions, expected tools, arguments and facts. |
| `fpl-agent-v2.manifest.json` | Snapshot identity, file hashes and reference checks. |
| `fpl-agent-v2.references.json` | Executed tool arguments and results used to check references. |
| `archive/fpl-agent-v2-post-gw6.jsonl` | Unchanged dataset used by `post-gw6-01`. |
| `fpl-agent-v1.jsonl` | Earlier dataset for the pre-GW6 snapshot. |

Player and club IDs are explicit where a tool needs them. The current agent
has no name-resolution or league-standings tool. The clarification and refusal
cases test those limits, account actions and unsupported guarantees.

Observed player results, rankings, prices, flags, news and fixture details
were checked against saved FPL API responses. Projections and optimiser
outputs were checked through the existing Python tools. They are model
estimates. Accept sensible rounding within 0.05 points when reviewing
projected values; observed counts, identities and monetary units must match.

Snapshots and run records remain under gitignored `data/evals/`. The current
snapshot ID is recorded in the manifest. Validate it before running:

```bash
.venv/bin/python -m pytest -q
make eval-baseline EVAL_RUN=pre-gw9-01
```

The second command calls the configured model and tracing service. It refuses
to overwrite existing run files. Use a new run name for subsequent experiments.
Run it after committing the Step 17 work so the run records the committed code.

Keep the cases, snapshot, references, model and prompt fixed within a comparison.
When refreshing data again, archive the old dataset before changing the active
file. A score difference between different datasets is not a measured model
or prompt improvement.

For the saved `post-gw6-01` review, use the archived post-GW6 dataset and the
original run files. Its dataset hash is
`9e37fb9b2a8c8c981644a79e6bb9da9a8e935064b6dcd68ea5daf7ce33911a5c`.
The recorded code commit had uncommitted changes; its exact source state was
not archived. That limits exact reproduction but does not prevent reviewing
the saved question, tool evidence and final answer.

Start with an automatic pass, an automatic failure and a refusal. Judge each
against the request, checked reference facts and tool evidence. Automatic tool
and argument scores do not establish final-answer correctness. Save manual
scores only after that review; then finish the other 17 cases.
