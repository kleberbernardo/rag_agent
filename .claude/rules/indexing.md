# Retrieval

`indexing/` is the part of this project worth reading first. It is also the
part where a careless change silently moves the evaluation score.

## The pipeline

```
ingestion   data/*.pdf ─▶ loader ─▶ splitter ─▶ embeddings ─▶ Postgres
                          pdf, md   per article   OpenAI      pgvector + FTS
                          txt, rst

query       question ─┬─▶ pgvector (meaning)  ─┐
                      └─▶ Postgres FTS (words) ─┴─▶ RRF ─▶ [rerank] ─▶ passages
```

## Modules

| Module | Does | Does not |
|---|---|---|
| `loader.py` | Read files into Documents | Know about chunking |
| `splitter.py` | Cut into chunks | Know about vectors |
| `database.py` | Connection pool, extensions, schema, indexes | Know about retrieval |
| `vector_store.py` | Store, count, search, reset | Know about fusion maths |
| `keyword.py` | One SQL query against the FTS index | Know about vectors |
| `hybrid.py` | `fuse()` and `tokenise()`, **no I/O** | Know where documents came from |
| `reranker.py` | The optional second pass | Know how retrieval happened |

`hybrid.py` having no I/O is deliberate. It is what makes the fusion testable
without a database and what lets the retrievers underneath be swapped.

## The two stages

**Retrieval decides what is in the pool and is judged on recall. Reranking
decides what comes out of it and is judged on precision.**

The line that ties them together, `vector_store.py::search`:

```python
wanted = max(settings.rerank_candidates, limit) if reranking_enabled() else limit
```

| Reranking | Retrieves | Returns |
|---|---|---|
| Off | `RETRIEVAL_K` (8) | 8 |
| On | `RERANK_CANDIDATES` (24) | 8 |

With no reranker the pool **is** the answer, so retrieving wider would be work
thrown away. With one, handing it exactly what it returns leaves it nothing to
choose between.

**Changing this changes evaluation results without any other visible change.**

## Fusion

Reciprocal rank fusion. Each document scores the sum of `1 / (60 + rank)`
across the lists it appears in.

**Fusing on rank rather than on score is the whole point.** A cosine distance
and a `ts_rank_cd` value are not on the same scale and cannot be added. This is
also what makes the keyword half replaceable: any retriever that returns an
ordered list can be fused, whatever it scores with.

`FUSION_POOL = 5`: each retriever is asked for five times what fusion returns.
Fusing two short lists only rewards what both already agreed on, which is what
either would have found alone. **Measured:** the missing passage reaches the
top eight at a multiplier of five and not at three.

Identity across retrievers is `source + "::" + content`, the same shape as the
stored id.

## Why both retrievers

An embedding compares meaning, which is what lets a question find a passage
sharing none of its words. It also spreads a long article's signal across
everything the article discusses, so one sentence stating a deadline ranks
below whatever the article is mostly about.

Keyword search compares words. It cannot follow a paraphrase, and it does not
need to when the question names the terms the text uses. Article numbers,
paragraph marks and codes have identity rather than meaning, and an embedding
blurs exactly those.

**Measured on this corpus, same question:** rank 31 by embedding, rank 5 by
keyword.

## Tokenising

`tokenise()` lowercases, strips ordinal marks, decomposes with NFKD and drops
combining characters, then keeps `[a-z0-9]+`.

**The ordinal marks matter.** `º`, `ª` and `°` are compatibility characters
that decompose into letters, turning `§2º` into `2o` and hiding the passage
from a search for `§ 2`. This corpus is written in articles and paragraphs, so
it is full of them.

The tokens are joined with `|` into a tsquery. **OR, not AND**: a question is a
sentence and a passage is a fragment, so requiring every word would return
nothing for most real questions. Ranking decides which partial match is worth
reading.

Tokenising also means the tsquery parser only ever sees letters and digits, so
none of the operators it understands can reach it from a user's question.

## Idempotent ingestion

A chunk id is `sha256(source + "::" + content)`. Running ingestion twice
overwrites the same rows instead of duplicating the index.

This is also what would make ingestion safe to retry from a queue, where the
same message can be delivered more than once.

**`rag ingest --reset` is required** after changing the chunking strategy or
the embedding model: different text produces different ids, and the old chunks
would stay behind competing for retrieval.

## Chunking

`CHUNK_STRATEGY=articles` is adaptive. A source with fewer than three article
headings falls back to character splitting, so a plain markdown file is
unharmed.

Annexes and tables carry no article headings, so everything after the last
article arrives as one enormous block. `ARTICLE_MAX_CHARS` is the cap above
which such a block is split further.

**Measured:** 93% by characters, 97% by article.

`splitter.py` is at 52% coverage. The article paths are the under-tested ones.

## Reranking

Off by default, and the reason is measured. See
[decisions.md](decisions.md#1-the-reranker-stays-off). The package is a hard
dependency now, since the guardrails brought torch anyway; only the 2.2 GB of
weights are deferred to first use.

`Reranker` is a Protocol with one method. `PassThroughReranker` exists so that
enabling the second pass is configuration rather than a branch at every call
site. `CrossEncoderReranker` loads the model on first use, not at import, and
holds it: loading costs seconds, scoring costs milliseconds.

Adding a provider (Cohere, a reranking service over HTTP) means writing a class
with a `rerank()` method. Nothing else changes.

Ingestion also runs the injection scan. See
[guardrails.md](guardrails.md#indirect-injection-is-the-rag-specific-risk).
