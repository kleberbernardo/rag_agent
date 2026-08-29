"""Chat model factory."""

from __future__ import annotations

from langchain_openai import ChatOpenAI

from rag_agent.config import get_settings


def build_chat_model() -> ChatOpenAI:
    """Create the chat client from the active settings."""
    settings = get_settings()
    return ChatOpenAI(
        model=settings.chat_model,
        temperature=settings.temperature,
        api_key=settings.openai_api_key,
    )
