# Observability

Langfuse, not LangSmith. See
[decisions.md](decisions.md#3-langfuse-not-langsmith).

## It turns itself on

```python
@property
def tracing_enabled(self) -> bool:
    return bool(public_key and secret_key)
```

Both keys present means tracing is on. Neither is present means every call in
`observability/tracing.py` returns `None` or an empty list and the application
runs unchanged.

**There is no `--trace` flag and there should not be one.** Adding a switch for
something already implied by configuration is anti-pattern A, see
[conventions.md](conventions.md).

## What Langfuse is used for

| Feature | Where |
|---|---|
| Traces | `build_callbacks()`, passed into every agent run |
| Scores | `record_score()`, one per metric per evaluation case |
| Datasets | `evaluation/experiments.py`, `rag dataset push` |
| Prompt management | `fetch_prompt()` / `publish_prompt()` |

Every run carries metadata: session id, tags, knowledge domain, chat model,
embedding model and `RETRIEVAL_K`. That is what makes a trace attributable to a
configuration months later.

## Prompt management

Four prompts are managed under the `production` label:

| Name | Used by |
|---|---|
| `rag-agent-system` | The agent's system prompt |
| `rag-agent-search-tool` | The search tool's description |
| `rag-agent-calculator-tool` | The calculator's description |
| `rag-agent-judge` | The `faithfulness` rubric |

`prompts/templates.py` holds the literal templates. They are **both** what
`rag prompt push` publishes **and** the fallback used when Langfuse is
unreachable. There is one source of truth, not two.

`{{domain}}` is substituted from `KNOWLEDGE_DOMAIN`. That is what keeps the
agent domain agnostic: pointing it at another corpus is configuration, not
code.

`PROMPT_CACHE_SECONDS` bounds how stale a fetched prompt can be. Moving the
`production` label in the Langfuse UI is how a prompt is deployed or rolled
back, with no redeploy.

**When adding a prompt:** add the template to `prompts/templates.py` and its
name to the publish list, so `rag prompt push` and the fallback stay in step.

## Cost

`observability/pricing.py` maps a model name to a price per token and returns
`None` for a model it does not know, rather than guessing. Every answer reports
latency, token usage and estimated cost.

**When changing `CHAT_MODEL`, check the pricing table.** An unknown model
silently reports no cost.

## Logging

`setup_logging()` writes to `LOG_DIR` and to the terminal. `--verbose` on any
command raises the level.

## Flushing

`flush()` must be called before the process exits, or buffered traces are lost.
The CLI does this at the end of every command; the API does it in the lifespan
shutdown. **A new entry point has to do the same.**
