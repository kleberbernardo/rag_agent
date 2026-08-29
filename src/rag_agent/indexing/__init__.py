"""Offline pipeline: load documents, split them, store them as vectors."""

from rag_agent.indexing.loader import SUPPORTED_SUFFIXES, load_documents
from rag_agent.indexing.splitter import split_documents
from rag_agent.indexing.vector_store import (
    count_documents,
    get_vector_store,
    index_documents,
    search,
)

__all__ = [
    "SUPPORTED_SUFFIXES",
    "count_documents",
    "get_vector_store",
    "index_documents",
    "load_documents",
    "search",
    "split_documents",
]
