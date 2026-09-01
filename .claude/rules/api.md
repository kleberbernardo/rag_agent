# HTTP API

`rag serve` starts Uvicorn on :8080. Interactive docs at `/docs`.

## Routes

| Method | Path | Tag |
|---|---|---|
| GET | `/health` | ops |
| GET | `/status` | ops |
| POST | `/ask` | agent |
| POST | `/chat` | agent |
| DELETE | `/chat/{session_id}` | agent |
| POST | `/feedback` | agent |

`/ask` is stateless. `/chat` carries a session id and remembers.

## Failure mapping

The API never leaks a driver stack trace. Each condition maps to a status and
a message naming what to do:

| Situation | Response |
|---|---|
| Empty index | `503` naming the ingestion step |
| Postgres unreachable | `503` naming the address it tried, password removed |
| Malformed body | `422` from the schema |
| Missing or wrong API key | `401`, when `API_KEY` is set |
| Unknown session on delete | `404` |

## Authentication

`API_KEY` empty means the API is open. Set it and every request needs the
`X-API-Key` header.

The comparison uses `hmac.compare_digest`, not `==`. A plain comparison returns
as soon as two bytes differ, which leaks the key one byte at a time to anyone
timing the response.

The dependency is applied to the whole router, not per route:

```python
app.include_router(router, dependencies=[Depends(require_api_key)])
```

Adding a route therefore protects it automatically. **A route added outside
this router is unauthenticated.**

## Dependencies

Injected with `Annotated[X, Depends(...)]`:

```python
SettingsDep = Annotated[Settings, Depends(get_settings)]
FeedbackDep = Annotated[FeedbackStore, Depends(get_feedback)]
SessionsDep = Annotated[SessionStore, Depends(get_sessions)]
```

That is what lets the tests replace the store without patching a module global.

## Sessions

`SessionStore` is an ABC with two implementations, chosen by
`SESSION_BACKEND`:

| Backend | When |
|---|---|
| `memory` | Default. A dict in the process that served the request |
| `redis` | Shared across replicas, survives a restart |

**A `ChatSession` cannot be pickled.** The compiled graph holds local closures
and pickling raises `Can't get local object
'CompiledStateGraph.attach_node.<locals>._get_updates'`.

`RedisSessionStore` therefore persists **only `messages_to_dict()` as JSON**
and rebuilds the session on read. If you add state to `ChatSession` that is not
in the message history, it will not survive a round trip through Redis.

`SESSION_TTL_SECONDS` expires idle conversations. The in-memory store evicts
the oldest instead.

## Not there yet

Deliberately absent, and worth knowing before claiming the API is
production ready:

- No rate limiting
- No CORS configuration
- Single Uvicorn process, no `--workers`
- `/health` exists, but there is no separate readiness probe
- No per-tenant isolation or permission-aware retrieval
