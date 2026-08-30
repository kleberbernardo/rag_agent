# Evaluation runs

One report per execution, kept so a change can be judged by its effect rather
than by intuition. Each file records the model, the embedding model and
`retrieval_k` next to the score, because a number without its configuration
cannot be compared to the next one.

Read them in order and the reasoning behind the current settings is visible.

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
