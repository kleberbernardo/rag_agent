# Architecture

## The map

```
                    ┌─────────────┐    ┌─────────────┐
   entry            │  cli/       │    │  api/       │
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
| `cli/` | Nine Typer commands, one module per group | See below |
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

## cli/ is a package, one module per group of commands

It was a single module of 742 lines, which is what a file becomes when every
new command is appended to the end of the last one.

| Module | Holds |
|---|---|
| `__init__.py` | The Typer application, assembled from the rest |
| `options.py` | Every shared flag, defined once |
| `console.py` | The terminal, and the checks a command runs before working |
| `indexing.py` | `ingest`, `sources`, `status` |
| `asking.py` | `ask`, `chat` |
| `evaluating.py` | `eval`, and the tables both its paths print |
| `prompting.py` | `prompt show`/`push`, `dataset push` |
| `serving.py` | `serve` |

**Commands are registered, not re-declared.** Each module owns a `Typer()`
holding its own, and `__init__.py` folds them in. A new group is a new module
and one line.

The largest piece is now `evaluating.py` at 281 lines, and the whole package
is 921 across eight files.

**A flag lives in `options.py`, not next to the command.** A flag defined
beside its command is defined again beside the next command that wants it, and
the two drift. `--verbose` means the same thing everywhere precisely because
there is one of it.

## Allowed dependencies between packages

```
cli/     ──▶ agent, indexing, evaluation, prompts, guardrails, observability
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
