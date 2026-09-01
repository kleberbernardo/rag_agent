"""The vector store: persisting chunks as vectors and searching them.

Postgres with pgvector holds the embeddings, and the same rows answer keyword
search through the full text index. One database means the vector and the
metadata are written in the same transaction and cannot drift apart, and it
means the operational burden is a database the organisation already runs.
"""

from __future__ import annotations

import hashlib
import logging

from langchain_core.documents import Document
from langchain_postgres import PGVector
from sqlalchemy import text

from rag_agent.config import SearchStrategy, get_settings
from rag_agent.indexing.database import (
    COLLECTION_TABLE,
    EMBEDDING_TABLE,
    DatabaseUnavailableError,
    describe_database,
    ensure_extensions,
    ensure_search_indexes,
    get_engine,
    verify_connection,
)
from rag_agent.indexing.hybrid import FUSION_POOL, fuse, identity
from rag_agent.indexing.keyword import keyword_search
from rag_agent.providers import build_embeddings
from rag_agent.types import SearchHit

logger = logging.getLogger(__name__)

__all__ = [
    "DatabaseUnavailableError",
    "count_documents",
    "describe_location",
    "get_vector_store",
    "index_documents",
    "reset_index",
    "search",
]

_COUNT = text(
    f"""
    SELECT count(*)
    FROM {EMBEDDING_TABLE} AS embedding
    JOIN {COLLECTION_TABLE} AS collection
      ON embedding.collection_id = collection.uuid
    WHERE collection.name = :collection
    """
)


def get_vector_store() -> PGVector:
    """Open the vector store described by the current settings.

    The extensions and the text search configuration are ensured on the way
    in. They are idempotent, and doing it here means a fresh database becomes
    usable by being pointed at, rather than by remembering a setup command.
    """
    settings = get_settings()

    verify_connection()
    ensure_extensions()

    return PGVector(
        embeddings=build_embeddings(),
        connection=get_engine(),
        collection_name=settings.collection_name,
        # Declaring the width turns the column into a fixed-size vector, which
        # is what an approximate index can be built on. Left undeclared, the
        # column is unconstrained and every search reads every row.
        embedding_length=settings.embedding_dimensions,
        use_jsonb=True,
        create_extension=False,
    )


def index_documents(chunks: list[Document]) -> int:
    """Embed the chunks and store them. Returns how many were indexed."""
    if not chunks:
        logger.warning("Nothing to index.")
        return 0

    store = get_vector_store()
    store.add_documents(documents=chunks, ids=[_stable_id(chunk) for chunk in chunks])

    # The tables exist only once something has been written to them, so this
    # is the first moment the indexes can be built.
    ensure_search_indexes()

    logger.info("Indexed %d chunk(s) in %s", len(chunks), describe_location())
    return len(chunks)


def search(query: str, k: int | None = None) -> list[SearchHit]:
    """Return the k chunks most relevant to the query.

    In `vector` mode this is nearest-neighbour on the embedding, and the hits
    carry their distance. In `hybrid` mode a keyword ranking is fused with it,
    and the distance is no longer meaningful for the fused list: two rankings
    are merged by position, not by score, because a cosine distance and a text
    search rank are not on the same scale.
    """
    settings = get_settings()
    limit = settings.retrieval_k if k is None else k

    if settings.search_strategy is SearchStrategy.VECTOR:
        scored = get_vector_store().similarity_search_with_score(query, k=limit)
        return [SearchHit(document=document, distance=distance) for document, distance in scored]

    pool = limit * FUSION_POOL
    scored = get_vector_store().similarity_search_with_score(query, k=pool)

    by_keyword = keyword_search(query, pool)
    if not by_keyword:
        return [
            SearchHit(document=document, distance=distance) for document, distance in scored[:limit]
        ]

    by_vector = [document for document, _ in scored]
    distances = {identity(document): distance for document, distance in scored}

    fused = fuse([by_vector, by_keyword], limit=limit)

    # A document the keyword search contributed has no distance of its own.
    # Reporting the worst seen keeps the field honest rather than inventing a
    # number that would read as a similarity.
    fallback = max(distances.values(), default=0.0)
    return [
        SearchHit(document=document, distance=distances.get(identity(document), fallback))
        for document in fused
    ]


def count_documents() -> int:
    """How many chunks are currently indexed."""
    verify_connection()

    with get_engine().connect() as connection:
        try:
            total = connection.execute(
                _COUNT, {"collection": get_settings().collection_name}
            ).scalar()
        except Exception:
            # Nothing has been indexed yet, so langchain-postgres has not
            # created its tables. An empty index is the honest answer.
            return 0

    return int(total or 0)


def reset_index() -> None:
    """Drop every indexed chunk.

    Ingestion is idempotent for identical chunks, but changing the chunking
    strategy produces different text and therefore different ids. Without a
    way to clear the collection, the old chunks stay behind and compete for
    retrieval against the new ones.
    """
    get_vector_store().delete_collection()
    logger.info("Cleared the index at %s", describe_location())


def describe_location() -> str:
    """Where the index lives, for diagnostics and log messages."""
    return describe_database()


def _stable_id(chunk: Document) -> str:
    """Derive a deterministic id from the chunk's source and content.

    This is what makes ingestion idempotent: running it twice overwrites the
    same records instead of duplicating the whole index. It is also what makes
    the ingestion safe to retry from a queue, where the same message can be
    delivered more than once.
    """
    raw = f"{chunk.metadata.get('source', '')}::{chunk.page_content}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
