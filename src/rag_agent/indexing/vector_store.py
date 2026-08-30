"""The vector store: persisting chunks as vectors and searching by meaning.

Two deployment modes share one interface. Embedded keeps the index in a local
file and needs nothing running; server talks to a standalone Chroma over HTTP,
which is what lets storage scale and restart independently of the application.
"""

from __future__ import annotations

import hashlib
import logging

from langchain_chroma import Chroma
from langchain_core.documents import Document

from rag_agent.config import Settings, VectorStoreMode, get_settings
from rag_agent.providers import build_embeddings
from rag_agent.types import SearchHit

logger = logging.getLogger(__name__)


class VectorStoreUnavailableError(RuntimeError):
    """The configured Chroma server could not be reached."""


def get_vector_store() -> Chroma:
    """Open the vector store described by the current settings."""
    settings = get_settings()

    if settings.vector_store_mode is VectorStoreMode.SERVER:
        return _open_server_store(settings)
    return _open_embedded_store(settings)


def index_documents(chunks: list[Document]) -> int:
    """Embed the chunks and store them. Returns how many were indexed."""
    if not chunks:
        logger.warning("Nothing to index.")
        return 0

    store = get_vector_store()
    store.add_documents(documents=chunks, ids=[_stable_id(chunk) for chunk in chunks])

    logger.info("Indexed %d chunk(s) in %s", len(chunks), describe_location())
    return len(chunks)


def search(query: str, k: int | None = None) -> list[SearchHit]:
    """Return the k chunks closest in meaning to the query.

    Smaller distance means closer. The query is embedded by the same model
    used at indexing time, which is what makes the comparison meaningful.
    """
    limit = get_settings().retrieval_k if k is None else k
    results = get_vector_store().similarity_search_with_score(query, k=limit)

    return [SearchHit(document=document, distance=distance) for document, distance in results]


def count_documents() -> int:
    """How many chunks are currently indexed."""
    return len(get_vector_store().get(include=[])["ids"])


def reset_index() -> None:
    """Drop every indexed chunk.

    Ingestion is idempotent for identical chunks, but changing the chunking
    strategy produces different text and therefore different ids. Without a
    way to clear the collection, the old chunks stay behind and compete for
    retrieval against the new ones.
    """
    store = get_vector_store()
    store.delete_collection()
    logger.info("Cleared the index at %s", describe_location())


def describe_location() -> str:
    """Where the index lives, for diagnostics and log messages."""
    settings = get_settings()

    if settings.vector_store_mode is VectorStoreMode.SERVER:
        return f"chroma://{settings.chroma_host}:{settings.chroma_port}"
    return str(settings.vector_store_dir)


def _open_embedded_store(settings: Settings) -> Chroma:
    """Open the on-disk store, creating its directory if needed."""
    settings.vector_store_dir.mkdir(parents=True, exist_ok=True)

    return Chroma(
        collection_name=settings.collection_name,
        embedding_function=build_embeddings(),
        persist_directory=str(settings.vector_store_dir),
    )


def _open_server_store(settings: Settings) -> Chroma:
    """Connect to a standalone Chroma server.

    A connection failure is translated on the spot: the driver's own error
    names an internal endpoint and tells the reader nothing about which knob
    to turn.
    """
    import chromadb

    try:
        client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        client.heartbeat()
    except Exception as error:
        msg = (
            f"Não foi possível conectar ao Chroma em "
            f"{settings.chroma_host}:{settings.chroma_port}. "
            f"Suba o servidor (docker compose up -d chroma) ou volte para "
            f"VECTOR_STORE_MODE=embedded."
        )
        raise VectorStoreUnavailableError(msg) from error

    return Chroma(
        client=client,
        collection_name=settings.collection_name,
        embedding_function=build_embeddings(),
    )


def _stable_id(chunk: Document) -> str:
    """Derive a deterministic id from the chunk's source and content.

    This is what makes ingestion idempotent: running it twice overwrites the
    same records instead of duplicating the whole index.
    """
    raw = f"{chunk.metadata.get('source', '')}::{chunk.page_content}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
