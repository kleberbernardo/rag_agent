# Evaluation

Unit tests prove the code does what it was written to do. Nothing there says
whether the agent answers correctly, and that is the question that decides
whether a change to the prompt, the chunking or the model made things better
or worse.

```bash
rag eval                     # the whole suite
rag eval --limit 5           # a quick sample
rag eval --min-score 0.90    # fail below 90%
```

## `dataset.json`

Twenty-nine questions. Twenty-five answerable, and **four deliberately outside
the corpus**.

The four are the important ones. They measure whether the agent admits it does
not know instead of inventing an answer, which nothing else in the project can
detect.

Every fact was read out of the indexed PDFs, not written from memory. Each
case carries the file the answer lives in, the number or term that has to
appear, and a reference answer.

Adding a case is how the suite grows: when the agent gets something wrong in
real use, that question belongs here, and it never regresses unnoticed again.

## `results/`

One report per execution. Each records the model, the embedding model and
`retrieval_k` next to the score, because a number without the configuration
behind it cannot be compared to the next one.

Read in order, they show how the current settings were reached.

| Report | Cases | Score | What was being tested |
|---|---|---|---|
| `20260830-195934` | 29 | 82% | Baseline. `k=4`, character chunking. Five answers cited the right file with the deadline from a neighbouring clause. |
| `20260830-200732` | 29 | 86% | `k=8`. More passages in context, two fewer wrong deadlines. |
| `20260830-200916` | 29 | 93% | A prompt rule capping retries. One out-of-corpus question had been searched until the context window overflowed. |
| `20260830-202318` | 5 | 80% | Sample run, five cases only. |
| `20260830-202715` | 29 | 93% | Confirmation after disambiguating a dataset question that had been graded wrong for a correct answer. |
| `20260830-202941` | 5 | 100% | Sample run, five cases only. |
| `20260830-203448` | 29 | **21%** | **Not a regression.** Article chunking put `Art. N` into the source label and broke the parser the metric uses to read it. Retrieval read 12% on a system that had improved: `fato` rose to 96% in the same run. |
| `20260830-203653` | 29 | 97% | The parser fixed. Article chunking measured properly. |
| `20260830-212255` | 29 | 97% | Groundedness added, at 100%. The current reference. |

The `21%` row is worth keeping. A metric can break while the system improves,
and the only thing that caught it was one number moving the wrong way while
another moved the right way.

## The metrics

| Metric | Question it answers |
|---|---|
| retrieval | Did the search return the right document? |
| citação | Did the answer name the right source? |
| fato | Did the expected number or term appear? |
| recusa | Outside the corpus, did it admit so? |
| fundamentação | Did every number come from what the agent read? |

All five are deterministic. No second model grades anything, so the same
answer always produces the same score and grading costs nothing.

The main README explains each one, how they relate to the names RAGAS and
LangSmith use, and where their limits are.
