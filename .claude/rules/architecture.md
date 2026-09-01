# Architecture

## The map

```
                    ┌─────────────┐    ┌─────────────┐
   entry            │  cli.py     │    │  api/       │
                    │  Typer      │    │  FastAPI    │
                    └──────┬──────┘    └──────┬──────┘
                           └────────┬─────────┘
                                    ▼
   application               agent/service.py       ← the only layer both call
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
   safety                     guardrails/         ← runs from service.py,
                        refused in · flagged out     so every interface is covered
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
   domain        prompts/         tools/       observability/
                 Langfuse      search + calc      Langfuse
                                    │
                                    ▼
   data                         indexing/
                     loader → splitter → vector_store → keyword
                                    │
                                    ▼
                            Postgres + pgvector
```

## The rule that holds it together

**`agent/service.py` does not know a terminal or HTTP exists.** That is why the
CLI and the API are thin wrappers rather than two implementations of the same
agent.

When adding a new interface (a worker, a bot, a scheduled job), it calls
`ask()` or `ChatSession`. If you find yourself changing `service.py` to
accommodate it, interface logic has probably ended up in the wrong place.

## Packages

| Package | Responsibility | Rules |
|---|---|---|
| `indexing/` | Load, split, embed, search | [indexing.md](indexing.md), [database.md](database.md) |
| `agent/` | The LangGraph graph and the application service | [agent.md](agent.md) |
| `guardrails/` | What is refused on the way in, flagged on the way out | [guardrails.md](guardrails.md) |
| `tools/` | Functions the model may call | [agent.md](agent.md) |
| `prompts/` | Templates, and fetching them from Langfuse | [observability.md](observability.md) |
| `evaluation/` | Dataset, metrics, judge, experiments | [evaluation.md](evaluation.md) |
| `observability/` | Traces, scores, cost, logging | [observability.md](observability.md) |
| `api/` | HTTP, sessions, authentication, rate limiting | [api.md](api.md) |
| `cli.py` | Nine Typer commands | See below |
| `config.py` | Every tunable value, validated at boot | See below |
| `providers.py` | **Every OpenAI import in the project** | [swapping.md](swapping.md) |
| `types.py` | Dataclasses shared across layers | |

## config.py is the boundary

Every tunable value lives in one Pydantic Settings class. Each field is read
from the uppercase environment variable of the same name (`chat_model` ←
`CHAT_MODEL`) or from `.env`. An invalid value stops the application at boot
with a clear message.

**`get_settings()` is `lru_cache`d.** After `monkeypatch.setenv` in a test,
call `get_settings.cache_clear()` or the old value survives.

**When adding a setting**, add its name to the list of variables deleted by the
`isolated_environment` fixture in `tests/conftest.py`. Without that, the
developer's own environment leaks into the tests.

## cli.py needs splitting

742 lines and nine commands, the largest file in the project by a wide
margin. It is at 76% coverage now, exercised through Typer's `CliRunner`,
which runs a terminal command in-process with no subprocess.

Coverage was the urgent half and it is done. The split is not: the agreed plan
is a `cli/` package with one module per command group.

**Do not add a new command here before splitting it.** It grew from 634 to 742
while that sentence was already in this file.

## Allowed dependencies between packages

```
cli      ──▶ agent, indexing, evaluation, prompts, guardrails, observability
api      ──▶ agent, indexing, guardrails, observability
agent    ──▶ tools, prompts, providers, guardrails, observability
tools    ──▶ indexing, prompts
indexing ──▶ providers, config
evaluation ──▶ agent, observability
```

**`indexing/` never imports `agent/`.** **`agent/` never imports `api/` or
`cli`.** If you need to break one of those, the design is wrong.

Inside `indexing/`, `hybrid.py` performs no I/O at all: only `fuse()` and
`tokenise()`. That is what allows the retrievers underneath to be replaced
without rewriting how ties are broken.
