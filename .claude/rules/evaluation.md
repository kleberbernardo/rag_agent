# Evaluation

## One command

```bash
rag eval
```

There is no `--langfuse`. The command detects the platform from its own
settings. Adding a destination flag is anti-pattern A, see
[conventions.md](conventions.md).

| Langfuse configured | Not configured |
|---|---|
| Questions come from the dataset there | Questions come from `evals/dataset.json` |
| Scores go back, one per metric per case | A report is written to `evals/results/` |

**Either way the agent and the metrics run on this machine.** No platform
re-executes the application. Langfuse's own documentation is explicit that its
evaluators score data already recorded on traces and never re-run your code.
That division is the standard one.

```
1. read the 29 questions       Langfuse, or the file
2. answer each one             this machine, always
3. score six metrics           this machine, always
4. send the scores             Langfuse, one per metric per case
5. print the table             this terminal, always
```

## The six metrics

| Metric | Asks | Kind |
|---|---|---|
| `retrieval` | Did the right document come back | reference based |
| `citation` | Does the answer name the right source | reference based |
| `correctness` | Is the expected number or term present | reference based |
| `refusal` | Did it admit not knowing, outside the corpus | reference based |
| `groundedness` | Did every number come from what it read | reference free |
| `faithfulness` | Does the sentence match the passage | **model graded** |

**Metric names are English everywhere**, including in Langfuse. Do not
translate them.

**Five are deterministic and one is not.** `faithfulness` is judged by a model
and drifts between runs. A single run at 100% is not a guarantee of the next.
Say so whenever quoting the score.

Six is the number. Adding a seventh is
[a settled decision](decisions.md#4-six-metrics-not-more).

## The dataset

`evals/dataset.json`, 29 cases. **Four have no answer in the corpus**, and they
are what makes `refusal` measurable. Do not delete them for being "wrong".

Case fields: `id`, `question`, `answerable`, `expected_source`,
`expected_facts`, `reference_answer`, `tags`.

Duplicate ids are rejected at load time.

`rag dataset push` uploads it to Langfuse.

## The judge

`evaluation/judge.py` is a separate model call with structured output
(a Pydantic `_Verdict`). Its rubric is a managed prompt, `rag-agent-judge`, so
it is versioned like the others.

**It is one metric, not a layer over the others.** The other five never touch
it. `--no-judge` skips it, which is the only way to make `rag eval` cost
nothing beyond the answers themselves.

## Every run records its configuration

`evaluation/configuration.py` captures the model, chunking strategy,
`RETRIEVAL_K`, and the prompt hash, source and version. **A score without its
configuration is not comparable to anything.**

`rag eval --compare <report>` diffs two runs, including the configuration
diff, so a score change can be attributed.

## Regression that shaped the code

The suite once dropped to 21% after a chunking change. The cause was not the
chunking: adding `Art. N` to the source label had broken the metric's regex.

It was caught because `faithfulness` went **up** while `retrieval` collapsed,
which is impossible if retrieval had genuinely got worse.

The fix was the regex `\[fonte:\s*([^\],|]+)` plus three regression tests.
**Only the file name is captured**, because the article is useful in a citation
but must not be part of what the metric compares.

## In CI

`.github/workflows/evaluation.yml` is manual plus a weekly cron. **Never on
push**: every run reaches the real model, so it costs money and takes minutes.
The fast checks live in `ci.yml` and cover every push.

The weekly run exists because the corpus stops changing but the model does not.
A provider updating `gpt-4o-mini` underneath a frozen project moves the score
with no commit to blame.

**`OPENAI_API_KEY` is not set as a GitHub secret**, so that workflow currently
skips. Setting it is on the owner.
