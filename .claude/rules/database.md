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

## Bootstrap, and why it runs at query time

`ensure_extensions()` runs from `get_vector_store()`. Everything it does is
idempotent, and doing it there means a fresh database becomes usable by being
pointed at rather than by remembering a setup command.

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE TEXT SEARCH CONFIGURATION portuguese_unaccent (COPY = portuguese);
ALTER TEXT SEARCH CONFIGURATION portuguese_unaccent
  ALTER MAPPING FOR hword, hword_part, word WITH unaccent, portuguese_stem;
```

`CREATE TEXT SEARCH CONFIGURATION` has no `IF NOT EXISTS`, so existence is
checked against `pg_ts_config` first rather than swallowing a duplicate-object
error.

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

## Known gap

**There is no per-document delete.** Only `reset_index()`, which drops the
whole collection. Removing one source document from the index is not possible
today. This is a real hole for any real deployment and is on the backlog.

## Testing against it

`tests/conftest.py::requires_postgres` is a mark that skips when the database
is unreachable. Apply it to anything that opens the store.

The `temporary_index` fixture points at a throwaway collection named with a
uuid and drops it afterwards. A collection per test rather than a database per
test: the rows are scoped by collection anyway, and creating one costs a single
insert.

Unit tests never need Postgres. `pytest tests/unit` runs with nothing up.
