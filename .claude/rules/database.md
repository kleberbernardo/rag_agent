# Postgres

Postgres with pgvector is the only store. There is no embedded mode, so
**anything touching the index needs `docker compose up -d postgres`.**

## Connection

`DATABASE_URL` defaults to
`postgresql+psycopg://rag:rag@localhost:5432/rag`.

**The driver is named in the URL on purpose.** SQLAlchemy defaults to psycopg2,
which is not what is installed. `postgresql://` alone fails.

`get_engine()` is cached per process, with `pool_pre_ping=True`: one round trip
per checkout, in exchange for immunity to the connection that a database
restart or an idle timeout left dead in the pool.

`describe_database()` renders the URL with the password removed. **It reaches
logs, `rag status` and the API status response**, so never build that string by
hand somewhere else.

## Schema

langchain-postgres owns two tables, named as constants in `database.py`:

| Table | Holds |
|---|---|
| `langchain_pg_collection` | One row per collection, keyed by `COLLECTION_NAME` |
| `langchain_pg_embedding` | The chunks: `document`, `cmetadata` (jsonb), `embedding` |

Every raw statement in the project lives in `database.py` and `keyword.py`, so
an upgrade that renames those tables breaks in one place.

## Alembic owns the schema

| Owner | What | When |
|---|---|---|
| **Alembic** | `vector`, `unaccent`, the `portuguese_unaccent` configuration | `alembic upgrade head` |
| **langchain-postgres** | `langchain_pg_collection`, `langchain_pg_embedding` | First write |
| **The application** | The GIN and HNSW indexes | After the first write |

The split is not arbitrary: an index cannot be created before the table it is
on, and that table belongs to a library that creates it on demand.

```bash
alembic upgrade head        # prepare a database
alembic revision -m "..."   # start a change
alembic downgrade -1        # undo the last one
```

`migrations/env.py` reads `DATABASE_URL` through the settings object, so
`alembic.ini` holds a placeholder and no credential is ever in a tracked file.

**The application does not apply migrations.** It did once, and that is an
anti-pattern past one replica: processes starting together race to create the
same objects, and a long migration blocks every boot instead of one deployment
step. `verify_schema()` checks and fails naming the command; the compose file
runs a one-shot `migrate` service that the API waits on with
`service_completed_successfully`.

The marker for "migrations applied" is the text search configuration, because
it is the object this project owns that nothing else creates.

## portuguese_unaccent is not optional

Postgres's stock `portuguese` configuration stems but does not fold accents.
Measured against the running database:

| Configuration | "suspensão" → | "suspensao" → | Unaccented question finds accented text |
|---|---|---|---|
| `portuguese` | `suspensã` | `suspensa` | **No** |
| `portuguese_unaccent` | `suspensa` | `suspensa` | **Yes** |

`unaccent` sits ahead of `portuguese_stem` in the dictionary chain, so both
sides of every comparison are folded the same way. In a corpus written in
Portuguese this is not a detail.

## Indexes

`ensure_search_indexes()` runs **after the first write**, because neither index
can exist before langchain-postgres has created its tables.

| Index | On | Without it |
|---|---|---|
| `rag_agent_document_fts` | `GIN (to_tsvector('portuguese_unaccent', document))` | Every keyword query parses every stored document |
| `rag_agent_embedding_hnsw` | `HNSW (embedding vector_cosine_ops)` | pgvector is exact, which is correct and reads every row |

**The text search configuration name is interpolated into the SQL, not bound as
a parameter.** A bind parameter would stop the query expression matching the
index expression, and the GIN index would go unused. It is a module constant,
never user input.

`EMBEDDING_DIMENSIONS` must match the embedding model. Declaring the width is
what turns the column into a fixed-size vector, which is what HNSW can be built
on. `text-embedding-3-small` is 1536, `text-embedding-3-large` is 3072.

## Removing one document

`delete_source(name)` matches on `cmetadata->>'source'`, the file name the
loader recorded, and is idempotent: removing what is not there returns zero
rather than raising. `list_sources()` groups the index by document, which is
what makes the name available to type.

Re-ingesting overwrites a chunk whose text is unchanged, so it cannot undo a
deletion. A document taken out comes back only if its file is still in `data/`
and ingestion runs again.

There is deliberately no HTTP route for it: deleting is destructive and the
API has one key with no roles, so exposing it would turn a leaked key into a
lost index.

## Testing against it

`tests/conftest.py::requires_postgres` is a mark that skips when the database
is unreachable. Apply it to anything that opens the store.

The `temporary_index` fixture points at a throwaway collection named with a
uuid and drops it afterwards. A collection per test rather than a database per
test: the rows are scoped by collection anyway, and creating one costs a single
insert.

Unit tests never need Postgres. `pytest tests/unit` runs with nothing up.
