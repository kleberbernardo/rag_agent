"""Offline pipeline: load documents, split them, store them as vectors."""

from rag_agent.indexing.hybrid import forget_keyword_index, fuse, keyword_index, tokenise
from rag_agent.indexing.loader import SUPPORTED_SUFFIXES, load_documents
from rag_agent.indexing.splitter import split_documents
from rag_agent.indexing.vector_store import (
    VectorStoreUnavailableError,
    count_documents,
    describe_location,
    get_vector_store,
    index_documents,
    reset_index,
    search,
)

__all__ = [
    "SUPPORTED_SUFFIXES",
    "VectorStoreUnavailableError",
    "count_documents",
    "describe_location",
    "forget_keyword_index",
    "fuse",
    "get_vector_store",
    "index_documents",
    "keyword_index",
    "load_documents",
    "reset_index",
    "search",
    "split_documents",
    "tokenise",
]
