# Settled decisions

Each was taken after measuring, or after looking up what the market does. A
future Claude will read the code and want to "improve" some of them. **Do not
reopen one without a new measurement that contradicts the reason recorded
here.**

If you believe one of these is wrong, the way to say so is a number, not an
argument.

---

## 1. The reranker stays off

**Decision:** `RERANK_STRATEGY=none` is the default. The code exists and works.

**Reason:** a reranker fixes precision, not recall. It reorders what was
already retrieved and cannot repair a pool the answer is not in.

**Measured:** the only failure the suite had for weeks was recall. The passage
stating the suspension deadline sat at **rank 31 of 590** by embedding. With
`RETRIEVAL_K=8` a reranker would have been handed eight passages that did not
contain the answer, and would have returned eight that still did not. Hybrid
search is what fixed it.

**When to reopen:** when the retrieved pool is wide enough to contain the
answer but the answer is not near the top. That is the normal condition at
scale, and not the condition on this corpus.

**Cost of turning it on today:** one model pass per candidate, plus roughly
2 GB of torch, for a measured gain of nothing on a corpus where every metric
already reads 100%.

---

## 2. pgvector, not Qdrant

**Decision:** Postgres with pgvector is the only store.

**Reason:**
- Vectors and text live in the same rows, so keyword search needs no second
  system and no copy that goes stale.
- A chunk, its metadata and its vector are written in one transaction.
- Most organisations already run Postgres. This adds an extension, not a
  database to operate.
- Managed on RDS, Cloud SQL, Supabase and Neon.
- Debuggable with `SELECT`.

**Ceiling:** somewhere above 10M vectors, or heavy metadata filtering at high
query rates. Past that the answer is Qdrant, and the change is **one class**.
See [swapping.md](swapping.md).

**Do not reopen** while the corpus is smaller than that. It is
over-engineering.

---

## 3. Langfuse, not LangSmith

**Decision:** Langfuse for traces, scores, datasets and prompt management.

**Reason:** decided after comparing the two. Langfuse is open source and
self-hostable, which matters for a regulated institution, and it covers all
four functions in one platform.

**Consequence:** there is no local report duplicating what the platform holds.
When Langfuse is configured, Langfuse is where the results live.

---

## 4. Six metrics, not more

**Decision:** `retrieval`, `citation`, `correctness`, `refusal`,
`groundedness`, `faithfulness`. Not one more.

**Reason:** all six read 100% over 29 cases. Adding a metric now is noise, not
signal.

**Precedent:** a seventh metric, `premature_tool_calls`, was written and
**discarded before it shipped**. It fired equally on correct behaviour, because
numbers legitimately change form between the question and the answer
("500 milhões" becomes `500000000`, "15%" becomes `0.15`). A metric that does
not separate right from wrong is measured noise.

---

## 5. One evaluation command, with no destination flag

**Decision:** `rag eval`, and that is all. There is no `--langfuse`.

**Reason:** the command detects Langfuse from its own settings. A destination
flag would force the user to know where things run in order to use what is
already automatic.

**Context:** there was a phase with several evaluation commands and the result
was confusion. See [conventions.md](conventions.md), anti-pattern A.

---

## Smaller decisions, also measured

| Decision | Measured reason |
|---|---|
| `RETRIEVAL_K=8`, not 4 | 82% at k=4, 93% at k=8, same dataset |
| `CHUNK_STRATEGY=articles` | 93% by characters, 97% by article |
| `FUSION_POOL=5`, not 3 | At a multiplier of 3 the missing passage does not reach the top 8; at 5 it does |
| A search budget, not a distance threshold | The ranges overlap: worst valid question 0.97, best invalid one 0.84. A threshold cannot separate them, a budget can |
| `portuguese_unaccent`, not `portuguese` | The stock config does not fold accents: "suspensão" stems to `suspensã` and "suspensao" to `suspensa`, so a question without the accent finds nothing |
| `katanemolabs/Arch-Guard` for injection, not LLM Guard's default | 7/8 correct with 0 false positives, against 5/8 with 3. The default refuses every Portuguese question |
| Nothing is an optional extra any more | The guardrails need torch, so the argument for keeping the reranker optional disappeared with it |
