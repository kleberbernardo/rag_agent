"""LLM and embedding clients.

Every OpenAI import in the project lives here. Swapping providers means
rewriting this module and nothing else.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

from rag_agent.config import get_settings


def build_chat_model() -> ChatOpenAI:
    """Create the chat client from the active settings."""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.chat_model,
        temperature=settings.temperature,
        api_key=settings.openai_api_key,
    )


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
