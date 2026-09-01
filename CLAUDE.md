# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

An agentic RAG system over a corpus of Brazilian securities regulation (three
CVM resolutions, 590 chunks). LangChain and LangGraph decide when to search,
Postgres with pgvector answers, Langfuse records, and 29 graded questions say
whether any of it works.

It serves two purposes at once, and both shape how to work here:

1. **A portfolio piece.** Decisions have to be defensible out loud, which is
   why every non-obvious one is recorded with the measurement behind it.
2. **A reusable base.** The corpus, the model, the store and the interface are
   all expected to be swapped in future projects. Keeping those four swaps
   cheap is a design constraint, not a nicety.

## Language rule

**Everything written for a developer is in English. Everything written for the
person using the running program is in Portuguese.**

English: identifiers, docstrings, comments, `CLAUDE.md`, `.claude/rules/`,
`README.md`, `docs/`, test names, metric names.

Portuguese: CLI output, API error messages, `.env.example` comments, commit
messages.

**No em dashes in the README or the rules.** Use a comma, a colon or a full
stop.

## Read before changing

| File | Read it when |
|---|---|
| [.claude/rules/decisions.md](.claude/rules/decisions.md) | **Always.** Five decisions are settled and must not be reopened without a measurement |
| [.claude/rules/conventions.md](.claude/rules/conventions.md) | **Always.** Two anti-patterns the owner named explicitly |
| [.claude/rules/architecture.md](.claude/rules/architecture.md) | Touching more than one package |
| [.claude/rules/indexing.md](.claude/rules/indexing.md) | Anything about retrieval, chunking or fusion |
| [.claude/rules/database.md](.claude/rules/database.md) | Anything that writes SQL or touches the schema |
| [.claude/rules/agent.md](.claude/rules/agent.md) | The graph, the tools, or the search budget |
| [.claude/rules/evaluation.md](.claude/rules/evaluation.md) | Metrics, dataset, the judge |
| [.claude/rules/api.md](.claude/rules/api.md) | Routes, auth, sessions |
| [.claude/rules/observability.md](.claude/rules/observability.md) | Langfuse, prompts, cost, logging |
| [.claude/rules/swapping.md](.claude/rules/swapping.md) | Reusing this project on a different corpus, model, store or interface |
| [.claude/rules/deployment.md](.claude/rules/deployment.md) | Docker, CI, or shipping it anywhere |

## Commands

```bash
pip install -e ".[dev]"          # install, with test and lint tooling
docker compose up -d postgres    # required for anything that touches the store
```

| Task | Command |
|---|---|
| Unit tests, no infrastructure | `pytest tests/unit` |
| Everything except integration | `pytest -m "not integration"` |
| One file | `pytest tests/unit/test_search.py` |
| One test | `pytest tests/unit/test_search.py::TestPoolWidth::test_the_vector_only_strategy_skips_the_fusion_multiplier` |
| Coverage | `pytest --cov=rag_agent --cov-report=term-missing` |
| Lint, format, types | `ruff check src tests`, `ruff format src tests`, `mypy` |

The full suite takes about 7 minutes. `pytest tests/unit` is the fast loop.

Integration tests carry the `integration` mark and skip themselves unless both
a real `OPENAI_API_KEY` and a reachable Postgres are present. CI never runs
them.

### Running the application

```bash
rag ingest --reset    # rebuild the index; required after changing chunking or the embedding model
rag ask "..."         # one question
rag chat              # conversation with memory
rag status            # active configuration and chunk count
rag eval              # grade against 29 questions, ~2 min, ~US$0.02
rag serve             # FastAPI on :8080, docs at /docs
rag prompt push       # publish the four prompt templates to Langfuse
rag dataset push      # upload the evaluation dataset to Langfuse
```

`python main.py <command>` runs the CLI from a fresh clone without installing.

## The shape of the thing

```
   cli.py  ·  api/          two thin interfaces
        └────┬────┘
             ▼
      agent/service.py      knows nothing about terminals or HTTP
             │
    ┌────────┼────────┐
    ▼        ▼        ▼
 prompts/  tools/  observability/
             │
             ▼
         indexing/          loader → splitter → vector_store
             │
             ▼
     Postgres + pgvector
```

**The retrieval path is the part worth understanding first**, and the part
where a careless change silently moves the evaluation score:

```
question ─┬─▶ pgvector (meaning)   ─┐
          └─▶ Postgres FTS (words)  ─┴─▶ RRF fusion ─▶ [rerank] ─▶ passages
```

Details in [indexing.md](.claude/rules/indexing.md).

## The five things that break silently

1. **The retrieval pool width depends on whether reranking is on.** With it
   off, the pool is `RETRIEVAL_K` because the pool is the answer. Changing this
   moves evaluation results with no other visible change.

2. **`portuguese_unaccent` is not optional.** Postgres's stock `portuguese`
   config stems but does not fold accents, so a question written without an
   accent finds nothing.

3. **The search budget lives in the tool's closure**, not a ContextVar, because
   LangGraph runs tools in its own context. `ChatSession.send()` rebuilds the
   agent every turn, which is what resets it.

4. **`get_settings()` is `lru_cache`d.** After `monkeypatch.setenv`, call
   `get_settings.cache_clear()`. A new setting also needs its name added to the
   `isolated_environment` fixture in `tests/conftest.py`.

5. **A `ChatSession` cannot be pickled.** Redis storage persists only
   `messages_to_dict()` as JSON. State added outside the message history will
   not survive a round trip.

## Known gaps

Do not present these as solved:

| Gap | Note |
|---|---|
| `cli.py` is 634 lines at 0% coverage | Largest file. Split before adding a command |
| No per-document delete | Only `reset_index()`, which drops everything |
| `splitter.py` at 52% coverage | The article-splitting paths are under-tested |
| No rate limiting, CORS, or Uvicorn workers | See [api.md](.claude/rules/api.md) |
| `OPENAI_API_KEY` is not a GitHub secret | `evaluation.yml` silently skips |
