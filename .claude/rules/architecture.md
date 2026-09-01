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
   domain        prompts/         tools/       observability/
                 Langfuse      search + calc      Langfuse
                                    │
                                    ▼
   data                         indexing/
                        loader → splitter → vector_store
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
| `tools/` | Functions the model may call | [agent.md](agent.md) |
| `prompts/` | Templates, and fetching them from Langfuse | [observability.md](observability.md) |
| `evaluation/` | Dataset, metrics, judge, experiments | [evaluation.md](evaluation.md) |
| `observability/` | Traces, scores, cost, logging | [observability.md](observability.md) |
| `api/` | HTTP, sessions, authentication | [api.md](api.md) |
| `cli.py` | Eight Typer commands | See below |
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

634 lines, **0% coverage**, the largest file in the project. Eight commands,
plus table rendering and error handling, all in one module.

The agreed plan: turn it into a `cli/` package with one module per command
group, and cover it with Typer's `CliRunner`, which exercises a terminal
command without a subprocess.

**Do not add a new command here before splitting it.**

## Allowed dependencies between packages

```
cli      ──▶ agent, indexing, evaluation, prompts, observability
api      ──▶ agent, indexing, observability
agent    ──▶ tools, prompts, providers, observability
tools    ──▶ indexing, prompts
indexing ──▶ providers, config
evaluation ──▶ agent, observability
```

**`indexing/` never imports `agent/`.** **`agent/` never imports `api/` or
`cli`.** If you need to break one of those, the design is wrong.

Inside `indexing/`, `hybrid.py` performs no I/O at all: only `fuse()` and
`tokenise()`. That is what allows the retrievers underneath to be replaced
without rewriting how ties are broken.
