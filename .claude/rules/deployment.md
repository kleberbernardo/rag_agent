# Running and shipping

## Locally

```bash
pip install -e ".[dev]"
docker compose up -d postgres
rag ingest --reset
rag ask "..."
```

`OPENAI_API_KEY` is read from the environment or `.env`. On the owner's
machine it is a persistent Windows user variable, so it does not appear in
`.env` and a POSIX shell spawned by tooling may not see it.

## Docker Compose

Three services:

| Service | Image | Why |
|---|---|---|
| `postgres` | `pgvector/pgvector:pg17` | Vectors and full text search |
| `redis` | `redis:7-alpine` | Sessions shared across replicas |
| `api` | built from `Dockerfile` | The agent |

```bash
export OPENAI_API_KEY=sk-...
docker compose up -d
docker compose run --rm api ingest
curl localhost:8080/health
```

The API waits on `service_healthy` for both, or it would fail on the first
command. Postgres's healthcheck is `pg_isready`, not a port check: the
entrypoint starts the server once to run init scripts and restarts it, so an
open port is not yet the real server.

Extensions and the text search configuration are created by the application on
first use, so a fresh database needs no setup step.

## The image

Multi-stage, non-root, `~422 MB`. It serves the API by default and still runs
the CLI on demand:

```dockerfile
ENTRYPOINT ["rag"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]
```

The healthcheck is a `python -c urllib` call against `/health`.

**On size:** it was ~618 MB when the store was Chroma. `chromadb` pulled in
`kubernetes` (83 MB), `onnxruntime` (66 MB) and Rust bindings (57 MB), all of
it machinery for running Chroma as a server, which this container never did. A
Postgres client is a driver. That saving is a consequence, not an optimisation.

**Do not add `sentence-transformers` to the image.** torch is roughly 2 GB and
reranking is off by default. It is the `rerank` extra for that reason.

## CI

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | Every push and PR | ruff, ruff format, mypy, pytest, docker build |
| `evaluation.yml` | Manual, plus Mondays 06:00 | `rag eval` with score and cost thresholds |

`ci.yml` runs a matrix of ubuntu and windows with `fail-fast: false`, because a
Windows-only break is exactly what the matrix is for.

**Integration tests never run in CI.** They reach the real embeddings API, and
a public repository has no business holding an API key.

The docker job needs `docker/setup-buildx-action@v3`: the runner's default
buildx driver cannot export a cache, and `cache-to: type=gha` depends on the
container driver.

**`OPENAI_API_KEY` is not configured as a repository secret**, so
`evaluation.yml` currently skips. Setting it is on the owner.

## Deployment target

There is none yet, and Kubernetes would be the wrong answer if there were.

| Scale | Deploy |
|---|---|
| Demo | Docker Compose, which is what exists |
| One product, one team | The same image on Cloud Run, ECS Fargate or App Runner |
| Many services, high traffic | Kubernetes |

The same image runs in all three. Nothing is being left behind by not choosing
Kubernetes now, and that choice belongs to whoever operates it.

**What is genuinely missing regardless of target**, and cheap:

1. Uvicorn workers. It is a single process today.
2. A readiness probe separate from `/health`, reporting whether the database is
   reachable and the index is populated.

## Windows

`pip install -e ".[rerank]"` fails with `OSError: [Errno 2] No such file or
directory` on a torch header unless long path support is enabled:

```powershell
Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' `
  -Name LongPathsEnabled -Value 1
```

Nothing else in the project needs it. Terminal encoding is handled by
`PYTHONIOENCODING=utf-8`, which `main.py` sets for itself.
