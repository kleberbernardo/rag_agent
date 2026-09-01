"""The Postgres connection and the schema the retrieval layer depends on.

Two things live here that the rest of the package assumes are already true:
the extensions, and the text search configuration used by keyword search.

Postgres ships a `portuguese` configuration that stems but does not fold
accents, so "suspensão" and "suspensao" stem to different words and a question
written without the accent finds nothing. Folding them is a matter of putting
`unaccent` ahead of the stemmer in a configuration of our own, which is the
standard recipe and the reason this module exists at all.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

from rag_agent.config import get_settings

logger = logging.getLogger(__name__)

# The text search configuration built below. Both the stored column and the
# query must be parsed with the same one, or the stems will not match.
TEXT_SEARCH_CONFIG = "portuguese_unaccent"

# langchain-postgres owns these tables. Naming them here keeps every raw
# statement in one file, so an upgrade that renames them breaks in one place.
EMBEDDING_TABLE = "langchain_pg_embedding"
COLLECTION_TABLE = "langchain_pg_collection"

_FTS_INDEX = "rag_agent_document_fts"
_VECTOR_INDEX = "rag_agent_embedding_hnsw"


class DatabaseUnavailableError(RuntimeError):
    """The configured Postgres could not be reached."""


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """The connection pool, opened once per process.

    `pool_pre_ping` costs one round trip per checkout and buys immunity to the
    connection a database restart or an idle timeout left dead in the pool.
    """
    settings = get_settings()

    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
    )


def forget_engine() -> None:
    """Dispose of the pool, so the next caller opens a new one."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()


def verify_connection() -> None:
    """Fail early, and name the knob to turn.

    The driver's own error quotes a host and a port and says nothing about
    which command brings that host up.
    """
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        msg = (
            f"Não foi possível conectar ao Postgres em {describe_database()}. "
            f"Suba o banco (docker compose up -d postgres) ou ajuste DATABASE_URL."
        )
        raise DatabaseUnavailableError(msg) from error


def ensure_extensions() -> None:
    """Install the extensions the retrieval layer needs.

    `vector` stores the embeddings and `unaccent` feeds the text search
    configuration below. Both are idempotent, so this runs on every startup
    rather than living in a migration nobody remembers to apply.
    """
    statements = (
        "CREATE EXTENSION IF NOT EXISTS vector",
        "CREATE EXTENSION IF NOT EXISTS unaccent",
    )

    with get_engine().begin() as connection:
        for statement in statements:
            connection.execute(text(statement))

        _ensure_text_search_config(connection)


def _ensure_text_search_config(connection: object) -> None:
    """Create the accent-folding Portuguese configuration, once.

    CREATE TEXT SEARCH CONFIGURATION has no IF NOT EXISTS, so existence is
    checked first rather than swallowing the duplicate-object error.
    """
    exists = connection.execute(  # type: ignore[attr-defined]
        text("SELECT 1 FROM pg_ts_config WHERE cfgname = :name"),
        {"name": TEXT_SEARCH_CONFIG},
    ).first()

    if exists:
        return

    connection.execute(  # type: ignore[attr-defined]
        text(f"CREATE TEXT SEARCH CONFIGURATION {TEXT_SEARCH_CONFIG} (COPY = portuguese)")
    )
    connection.execute(  # type: ignore[attr-defined]
        text(
            f"ALTER TEXT SEARCH CONFIGURATION {TEXT_SEARCH_CONFIG} "
            f"ALTER MAPPING FOR hword, hword_part, word "
            f"WITH unaccent, portuguese_stem"
        )
    )
    logger.info("Created the text search configuration %s", TEXT_SEARCH_CONFIG)


def ensure_search_indexes() -> None:
    """Build the indexes both halves of the search depend on.

    Neither can exist before langchain-postgres has created its tables, which
    is why this runs after the first write rather than at startup.

    The GIN index is what keeps keyword search from parsing every stored
    document on every query. The HNSW index is the approximate nearest
    neighbour index for the vectors; without it pgvector is exact, which is
    correct and reads every row. Both are the difference between a corpus of
    hundreds and one of millions.
    """
    statements = (
        f"CREATE INDEX IF NOT EXISTS {_FTS_INDEX} ON {EMBEDDING_TABLE} "
        f"USING GIN (to_tsvector('{TEXT_SEARCH_CONFIG}', document))",
        f"CREATE INDEX IF NOT EXISTS {_VECTOR_INDEX} ON {EMBEDDING_TABLE} "
        f"USING HNSW (embedding vector_cosine_ops)",
    )

    with get_engine().begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def describe_database() -> str:
    """The database location with the password removed, for logs and status."""
    from sqlalchemy.engine import make_url

    return make_url(get_settings().database_url).render_as_string(hide_password=True)
