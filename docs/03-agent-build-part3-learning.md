# FPL Agent — Part 3: understand and own the implementation

Version 3, 30 October 2026.

**Goal:** I can follow one question through the agent, explain the important
boundaries, review its evidence and make one change that I understand.

The application already has substantial working code. Do not rebuild it from
scratch. Revisit one behaviour at a time, then make one learner-owned change.

The [original Part 3](03-agent-build-part3.md) remains the delivery roadmap.
Use this document for the FPL review work. Use `budget-system` for new agent
implementation practice. Keep the personal weekly FPL workflow active for the
[December league goal](03-agent-build-part3.md#personal-league-goal--december-2026).
Deployment and the public pilot come later; their old dates are postponed.

## Current agreement

Keep any independent drawing, AGENTS.md or understanding notes as learner work.
AI must not fill them in or mark a learning check complete without evidence.

On 28 October, the user delegated the 20 evaluation questions and reference
answers to AI. The updated `evals/fpl-agent-v2.jsonl` uses a fresh post-GW8
snapshot for GW9. References were checked against frozen tool results and
saved FPL responses. See [dataset instructions](../evals/README.md).

The AI-assisted Step 17 review and failure classification are complete for
`post-gw6-01`. Keep its original run files and archived post-GW6 dataset.
Commit the current code, prompt and review record before running the new
GW9 dataset. That run is a separate experiment with a new run name; it does
not measure improvement against a different snapshot and case set.

## What already exists

Repository check on 30 October 2026:

- Steps 13–16 have implementations: snapshots, tools, the agent loop and tracing.
- The Step 17 runner has saved `post-gw6-01`: 20 results, automatic scores and
  a run manifest. That proves the batch ran, not that every answer was correct.
- The 20-answer review and classified summary are saved as
  `post-gw6-01-reviews-v2.jsonl`, `post-gw6-01-reviewed-v2.jsonl` and
  `post-gw6-01-summary-v2.jsonl`. They retain the original scores and recorded answers.
- The AI-assisted review found 11/20 full-task passes, 15/20 fact-recall passes
  and 17/20 groundedness passes. Ten cases had a failing check; their primary
  categories include one strict-matcher evaluation defect. The no-answer error
  counts as a groundedness failure, not an unsupported-claim incident.
- The reusable result line is in `manual-eval-record.md`. Completion of the
  assisted review does not establish independent understanding of every case.
- The active 20-case dataset now uses a validated post-GW8 snapshot; the old
  dataset is preserved in `evals/archive/fpl-agent-v2-post-gw6.jsonl`.
- Steps 18 onward remain in the delivery roadmap.

These are software status statements. Your understanding of each part remains
unchecked until you demonstrate it. There is no need to pretend the code is
unfinished or delete it to make learning possible.

## How we will work

Use `$socratic-code-mentor` when you return for help. The shared user-wide
installation is at `~/.agents/skills/socratic-code-mentor/SKILL.md`. Codex
supports this user-level discovery location; restart the session if needed
\[3\]. The skill is also linked into Claude's user skills at
`~/.claude/skills/socratic-code-mentor/`. Keep the skill and its supporting
files in the user-wide directory, outside this repository.

For ChatGPT web or mobile, add the short personal-instructions version from
`~/.agents/skills/socratic-code-mentor/assets/chatgpt-custom-instructions.txt`
through the account's Personalization settings. Local skill files do not
change account settings on those surfaces \[4\].

The article separates the part the learner wants to practise from work they
can delegate. Here, the connections between components are part of the
learning target; AI must not automatically treat them as bookkeeping
\[1\], \[2\].

- You choose the current learning target and make its implementation attempt.
- AI asks one question and waits. It does not send the complete solution next
  to the question.
- If the concept is new, AI explains that concept before asking about it.
- If you remain stuck, AI changes the help: smaller input, clearer explanation
  or a short example. It does not keep rephrasing the same question.
- Each phase lists three important traps, in priority order. Add at most two
  more when needed. During mentoring, focus on the current phase only.
- AI can write supporting fixtures, tooling or tests that you delegate. When
  learning test design, you choose the expected behaviour before AI writes it.
- If you explicitly delegate a fix, AI makes that fix. Record the assistance;
  passing its tests does not complete your understanding check.

Use the existing CLI, debugger, REPL, saved results and trace viewer. Do not
build a new teaching UI, switch frameworks or add another agent service.

### One session: about 25–40 minutes

1. Choose the earliest unchecked phase and one uncertainty from your notes.
2. Read one relevant function and its caller. Stop expanding the reading list
   when you can state that function's inputs, output and side effects.
3. Predict one concrete result before running it.
4. Run a small check. Use fake model replies or existing saved data when live
   model behaviour is not the subject.
5. Write or repair one small behaviour in a scratch copy or synthetic fixture.
   Keep original code and frozen evidence intact.
6. Run the check again. Explain the result and predict a different input.

Stop when that behaviour is understood. A phase may take several sessions.
Do not open a second half-finished change to fill the remaining time.

## Phase L1 — follow one existing path

**Goal:** identify what one selected function receives, returns and calls.

**Do:**

1. Use your own drawing to choose one uncertain box.
2. Find its caller and write one real input and the expected output shape.
3. Predict the next function call, then check with the debugger or a saved run.
4. Reproduce one small part on a different input without copying its solution.

**Done when:** you can follow that section without AI supplying the file names,
and distinguish a returned value from printed output or a file write.

**Traps, highest priority first:**

- Recognising a function name without knowing its inputs and output.
- Following every branch instead of the one selected path.
- Treating printed output as the function's returned value.

## Phase L2 — understand the frozen-data boundary

**Goal:** explain which saved data a question uses and why the result is dated.

**Do:**

1. Select an existing snapshot. Identify how the application selects it and
   checks it before using its data.
2. Predict what happens when a snapshot ID or file hash does not match.
3. Test that prediction on a disposable copy or a synthetic fixture.
4. Write one small input or consistency check yourself. Do not implement a
   new hashing algorithm or rewrite the snapshot system.

**Done when:** you can show one accepted input and one rejected input, explain
why rejection happens before tool execution, and leave the original unchanged.

**Traps, highest priority first:**

- Mixing current FPL website facts with a past snapshot's facts.
- Changing the original snapshot instead of a disposable copy.
- Treating an older frozen experiment as invalid when a new GW finishes.

## Phase L3 — understand one tool contract

**Goal:** explain how one ordinary Python tool turns validated inputs into data.

**Do:**

1. Pick one existing tool. List the input fields and output fields it actually
   supports. Do not infer capabilities from the tool's name.
2. Follow one value from the selected snapshot to the returned result.
3. Predict a valid request and an invalid request. Invoke the tool without an LLM.
4. Reproduce a small validation or field-mapping step in a scratch exercise.

**Done when:** you can explain who selects the snapshot, which values the
caller supplies, and what fails when a required value is missing or invalid.

**Traps, highest priority first:**

- Assuming the LLM received a field that the tool did not return.
- Looking up an ID without checking the relevant season and GW.
- Skipping validation because the input came from a saved file.

## Phase L4 — understand one model–tool exchange

**Goal:** explain how a requested tool call becomes an executed call and an answer.

**Do:**

1. Choose one saved run with a tool call. Identify the model's request, the
   executed function, its returned data and the final response.
2. Predict the message order and call count before replaying fake model replies.
3. Write or repair one message-handling branch in a scratch copy. Keep the
   rest of the working loop as support code.
4. Check one failure, such as an invalid argument or an exhausted call limit.

**Done when:** you can explain the matching tool-call ID, the stopping condition
and where one reported number came from. You can predict a different request.

**Traps, highest priority first:**

- Treating a requested tool call as successful execution.
- Continuing the model conversation without the matching tool result.
- Attributing a Python calculation to the LLM that explained it.

For a recommendation, follow one value into the existing projection and
optimisation functions. Identify the inputs and assumptions. Mastering every
statistical model is not a requirement for understanding this interface.

## Phase L5 — understand the trace of that exchange

**Goal:** connect a saved answer to evidence of what actually ran.

**Do:**

1. Open the trace for the same question you followed in L4.
2. Distinguish the run ID, case ID, tool-call ID, snapshot ID and trace ID.
3. Predict which observation records a model request and which records a tool.
4. Check a fake tracing failure. Reproduce one small metadata-selection or
   collection step yourself, without exposing private values.

**Done when:** you can find the request, tool result and final answer, and show
that failed tracing does not alter the application answer or repeat its work.

**Traps, highest priority first:**

- Recording private values or credentials in a trace.
- Treating an existing trace as proof that its answer is correct.
- Treating a saved trace ID as proof of delivery to Langfuse.

## Phase L6 — understand and complete one evaluation

**Goal:** judge answers from evidence and explain what each score measures.

**Do:**

1. Use the saved 20-answer run and its matching archived dataset first. Keep
   the question, reference facts, season, GW and snapshot together.
2. Inspect one case and its saved result. The user has delegated question and
   reference preparation; judging answers remains the learning target.
3. Predict a tool-selection score on synthetic records. Write that small check
   yourself and test a present and a missing required tool.
4. Review one successful answer, one failed answer and one refusal. Then apply
   the same criteria to the full 20-case run you choose to complete.
5. Save the reviews and use the existing merge and summary functions. Explain
   one aggregate rate by counting the relevant case records yourself.

For each answer, keep three sources separate:

- **Reference facts:** the checked answer for the selected frozen data.
- **Recorded evidence:** the tool results the model actually received.
- **User request:** what the answer needed to achieve.

Tool selection and argument validity are currently automatic checks. Fact
recall, groundedness and task success need your review. A tool request can
exist even when execution fails. An honest clarification can contain no false
claim while still failing to answer the original question.

For recommendation questions, define checkable criteria. The FPL website can
verify facts and rules; it cannot supply a guaranteed correct future transfer.
Check constraints, stated inputs, tool support and uncertainty. Treat later
realised points as a separate test of the projection or decision policy.

**Done when:** you can explain the three sample reviews, complete all 20
reviews, and connect the saved summary to its source cases and run manifest.
Unknown failure causes can remain labelled uncertain until investigated.

**Traps, highest priority first:**

- Changing questions or reference answers during a before/after comparison.
- Treating a passing tool or argument check as a correct final answer.
- Treating one realised match result as proof of a projection's reliability.

Keep `fpl-agent-v1.jsonl`, `archive/fpl-agent-v2-post-gw6.jsonl`, their
snapshots and old run files unchanged. The user-authorised refresh of active
`fpl-agent-v2.jsonl` has its own snapshot, references and metadata. Freeze this
new dataset during a comparison. Do not compare its aggregate rate directly
with an older dataset's rate as proof of improvement.

## Phase L7 — make one change you can defend

**Goal:** own one bounded implementation change, including its expected behaviour.

**Do:**

1. Choose one failure from your review. Write a hypothesis before receiving a fix.
2. Identify the smallest behaviour that needs to change and one check that
   should fail before the change. Inspect code where the evidence requires it.
3. Implement that behaviour yourself. Ask for hints or supporting test setup
   when needed; do not replace several components together.
4. Run the small check, relevant offline tests and the same fixed evaluation.
   Use a new run name and change only the chosen prompt or tool behaviour.
5. Write the observed difference, remaining failures and limits in your own words.

**Done when:** you can explain your change without AI, predict a new input and
show the unchanged baseline beside the new run. An unsuccessful experiment
still counts as learning if you can show what it tested and what happened.

**Traps, highest priority first:**

- Changing several components and losing the cause of a score difference.
- Delegating the learning target while marking it as independently understood.
- Treating one passing example as sufficient evidence for the whole change.

## Finish line

This learning plan ends when you can independently:

- follow one question across the important component boundaries;
- predict a valid and invalid input at those boundaries;
- separate an LLM choice, a Python calculation and a final factual claim;
- review and summarise a complete fixed run;
- implement and defend one small measured change.

You do not need to memorise the repository. You do need to know how to find
the relevant code, read its contract and check its behaviour.

Then return to the delivery roadmap. L7 supplies the learning work for Step 18;
model comparison, live team handling, server, pilot and optional Telegram stay
in their existing order. Before a pilot, revisit public-team freshness: a
pre-deadline transfer was not visible during the earlier Groß check. Do not
promise that public data always represents a user's latest private changes.

## Progress — learner evidence, not software status

- [ ] L1: one existing path followed independently.
- [ ] L2: frozen-data boundary tested and explained.
- [ ] L3: one tool contract demonstrated.
- [ ] L4: one model–tool exchange reproduced and explained.
- [ ] L5: one trace matched to its saved result.
- [ ] L6: one complete evaluation reviewed and summarised.
- [ ] L7: one learner-owned change checked against its baseline.

Only mark a phase after its demonstration. Do not tick it because its code
already exists or because AI completed a fix.

At the end of a session, you can append:

```text
Phase:
Function or behaviour I worked on:
What I predicted:
What I observed:
What I can now explain:
What I still cannot explain:
Next small action:
Assistance used:
```

AI may record progress you confirm. It must not fill your understanding notes
or replace your account of what you learned.

## References

1. O. Olguncu, “How to keep learning in the age of LLMs,” Oct. 4, 2026.
   [Online]. Available: https://ogzhanolguncu.com/blog/how-to-keep-learning-in-the-age-of-llms/
2. O. Olguncu, “socratic-code-mentor,” Oct. 4, 2026. [Online]. Available:
   https://gist.github.com/ogzhanolguncu/274e9974dc02942109ad70200f6d7b25
3. OpenAI, “Build skills,” accessed Oct. 26, 2026. [Online]. Available:
   https://learn.chatgpt.com/docs/build-skills
4. OpenAI, “Personalize ChatGPT,” accessed Oct. 26, 2026. [Online]. Available:
   https://learn.chatgpt.com/docs/personalize
