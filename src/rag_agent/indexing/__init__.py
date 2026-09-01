"""Offline pipeline: load documents, split them, store them as vectors."""

from rag_agent.indexing.database import (
    DatabaseUnavailableError,
    describe_database,
    ensure_extensions,
    ensure_search_indexes,
    forget_engine,
    get_engine,
    verify_connection,
)
from rag_agent.indexing.hybrid import fuse, tokenise
from rag_agent.indexing.keyword import keyword_search
from rag_agent.indexing.loader import SUPPORTED_SUFFIXES, load_documents
from rag_agent.indexing.reranker import (
    Reranker,
    RerankerUnavailableError,
    forget_reranker,
    get_reranker,
    reranking_enabled,
)
from rag_agent.indexing.splitter import split_documents
from rag_agent.indexing.vector_store import (
    count_documents,
    describe_location,
    get_vector_store,
    index_documents,
    reset_index,
    search,
)

__all__ = [
    "SUPPORTED_SUFFIXES",
    "DatabaseUnavailableError",
    "Reranker",
    "RerankerUnavailableError",
    "count_documents",
    "describe_database",
    "describe_location",
    "ensure_extensions",
    "ensure_search_indexes",
    "forget_engine",
    "forget_reranker",
    "fuse",
    "get_engine",
    "get_reranker",
    "get_vector_store",
    "index_documents",
    "keyword_search",
    "load_documents",
    "reranking_enabled",
    "reset_index",
    "search",
    "split_documents",
    "tokenise",
    "verify_connection",
]
