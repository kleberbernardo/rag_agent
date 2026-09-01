# Swap boundaries

This project is meant to be copied as the starting point for real work. The
owner expects to swap all four of the things below.

**Each swap should touch exactly the files listed and nothing else.** If a swap
starts spreading, that is a design defect worth fixing rather than working
around.

---

## 1. The corpus and the domain

Swapping the subject is meant to be **configuration, not code**.

| Change | Where |
|---|---|
| The documents | Replace `data/*`, record provenance in `docs/knowledge-base-sources.md` |
| What the corpus is about | `KNOWLEDGE_DOMAIN` in `.env` |
| Rebuild the index | `rag ingest --reset` |
| The questions | `evals/dataset.json`, then `rag dataset push` |

`KNOWLEDGE_DOMAIN` is substituted into `{{domain}}` in the system prompt and in
the search tool's description. That is the whole mechanism.

**What usually also needs attention:**

- `CHUNK_STRATEGY`. `articles` is adaptive and falls back to character
  splitting below three article headings, so a non-legal corpus is unharmed,
  but measure both.
- `evals/dataset.json` must keep cases that the corpus **cannot** answer, or
  `refusal` becomes unmeasurable.
- The prompts are written in Portuguese because the answers are. A corpus in
  another language means republishing the four templates.

**What must not change:** the metric names, which are English by decision.

---

## 2. The model or the provider

**Every OpenAI import in the project is in `providers.py`.** That is the only
file a provider swap rewrites.

```python
def build_chat_model() -> ChatOpenAI: ...
def build_embeddings() -> OpenAIEmbeddings: ...
```

To move to Anthropic, a local model, or anything else, return a different
LangChain client from those two functions. Everything downstream takes a
LangChain interface.

**What else to check:**

| Thing | Why |
|---|---|
| `EMBEDDING_DIMENSIONS` | Must match the new embedding model, or HNSW cannot be built |
| `rag ingest --reset` | Vectors from different models are not comparable |
| `observability/pricing.py` | An unknown model silently reports no cost |
| `evaluation/judge.py` | Uses structured output; confirm the new model supports it |
| Retry and timeout | `MAX_RETRIES` and `REQUEST_TIMEOUT_SECONDS` are passed through from settings |

The chat model and the embedding model are separate settings and can come from
different providers.

---

## 3. The vector store

The store is reached through five functions in `vector_store.py`:
`get_vector_store`, `index_documents`, `search`, `count_documents`,
`reset_index`.

Keyword search is one SQL query in `keyword.py`. Fusion in `hybrid.py` **does
no I/O and does not change**: RRF fuses on rank, so any retriever that returns
an ordered list can be fused, whatever it scores with.

**To move to Qdrant, OpenSearch or Weaviate:**

1. Rewrite `vector_store.py` against the new client, keeping those five
   signatures.
2. Replace `keyword.py` with that engine's own keyword query. Qdrant and
   OpenSearch both have BM25 natively.
3. Delete or repoint `database.py`.
4. `hybrid.py`, `reranker.py`, `agent/`, `evaluation/` and `api/` are
   untouched.

**When it is worth it:** above roughly 10M vectors, or heavy metadata filtering
at high query rates. Not before. See
[decisions.md](decisions.md#2-pgvector-not-qdrant).

---

## 4. The interface

**`agent/service.py` knows nothing about a terminal or HTTP.** A new interface
is a wrapper around `ask()` or `ChatSession`, not a new agent.

| Target | What to write |
|---|---|
| API only | Drop `cli.py`; `api/` already stands alone |
| Worker or queue consumer | Call `ask()` per message. Ingestion is idempotent, so redelivery is safe |
| Chat bot | Use `ChatSession` with the platform's thread id as the session id |
| Scheduled job | Call `ask()`, then `flush()` before exiting |

**Two things any new entry point must do:**

1. Call `observability.flush()` before the process exits, or buffered traces
   are lost.
2. Let `ChatSession.send()` rebuild the agent per turn. That is what resets the
   search budget. See [agent.md](agent.md).

If the interface needs conversation state across processes, use
`SESSION_BACKEND=redis` and remember that only the message history survives
the round trip.
