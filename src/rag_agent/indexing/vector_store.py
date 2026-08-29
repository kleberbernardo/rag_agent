"""The vector store: persisting chunks as vectors and searching by meaning."""

from __future__ import annotations

import hashlib
import logging

from langchain_chroma import Chroma
from langchain_core.documents import Document

from rag_agent.config import get_settings
from rag_agent.providers import build_embeddings
from rag_agent.types import SearchHit

logger = logging.getLogger(__name__)


def get_vector_store() -> Chroma:
    """Open the on-disk vector store, creating it if needed."""
    settings = get_settings()
    settings.vector_store_dir.mkdir(parents=True, exist_ok=True)

    return Chroma(
        collection_name=settings.collection_name,
        embedding_function=build_embeddings(),
        persist_directory=str(settings.vector_store_dir),
    )


def index_documents(chunks: list[Document]) -> int:
    """Embed the chunks and store them. Returns how many were indexed."""
    if not chunks:
        logger.warning("Nothing to index.")
        return 0

    store = get_vector_store()
    store.add_documents(documents=chunks, ids=[_stable_id(chunk) for chunk in chunks])

    logger.info("Indexed %d chunk(s) in %s", len(chunks), get_settings().vector_store_dir)
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


def _stable_id(chunk: Document) -> str:
    """Derive a deterministic id from the chunk's source and content.

    This is what makes ingestion idempotent: running it twice overwrites the
    same records instead of duplicating the whole index.
    """
    raw = f"{chunk.metadata.get('source', '')}::{chunk.page_content}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
