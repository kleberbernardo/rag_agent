"""Embedding model factory."""

from __future__ import annotations

from langchain_openai import OpenAIEmbeddings

from rag_agent.config import get_settings


def build_embeddings() -> OpenAIEmbeddings:
    """Create the text-to-vector client from the active settings.

    The same model must be used for indexing and for searching: vectors
    produced by different models are not comparable.
    """
    settings = get_settings()
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        api_key=settings.openai_api_key,
    )
