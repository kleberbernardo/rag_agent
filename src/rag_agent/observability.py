"""Optional LLM tracing through Langfuse.

The local metrics in `types.RunMetrics` say what a run cost in total. A trace
says where it went: each model call, each tool, each retrieved passage, with
its own latency and token count.

Tracing is off unless both Langfuse keys are configured, and a broken or
unreachable Langfuse never breaks an answer -- observability that can take the
application down with it is worse than none.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from rag_agent.config import get_settings

logger = logging.getLogger(__name__)


@lru_cache
def _client() -> Any | None:
    """Create the Langfuse client once, or None when tracing is off."""
    settings = get_settings()

    if not settings.tracing_enabled:
        logger.debug("Tracing disabled: Langfuse keys are not configured.")
        return None

    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            base_url=settings.langfuse_host,
        )
        if not client.auth_check():
            logger.warning("Langfuse rejected the configured keys. Tracing disabled.")
            return None
    except Exception:
        logger.warning("Could not start Langfuse. Tracing disabled.", exc_info=True)
        return None

    logger.info("Tracing enabled: %s", settings.langfuse_host)
    return client


RUN_NAME = "rag.ask"

# Without a cap, a question the agent cannot satisfy makes it search again and
# again, each round adding passages to the history until the context window
# overflows and the whole call dies. Ten steps is well past any legitimate
# search-then-answer loop.
RECURSION_LIMIT = 10


def build_callbacks() -> list[Any]:
    """Callbacks to hand to the agent. Empty when tracing is off."""
    if _client() is None:
        return []

    try:
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]
    except Exception:
        logger.warning("Could not build the Langfuse callback.", exc_info=True)
        return []


def build_run_config(*, session_id: str) -> dict[str, Any]:
    """The config for one agent invocation, tracing included when it is on.

    Without a run name every trace lands in the dashboard called "LangGraph",
    and without a session id the turns of one conversation are unrelated rows.
    The metadata records which settings produced the run, so a trace from last
    week still explains itself.
    """
    config: dict[str, Any] = {
        "callbacks": build_callbacks(),
        "run_name": RUN_NAME,
        "recursion_limit": RECURSION_LIMIT,
    }

    if _client() is None:
        return config

    settings = get_settings()
    config["metadata"] = {
        "langfuse_session_id": session_id,
        "langfuse_tags": ["rag-agent", settings.vector_store_mode.value],
        "knowledge_domain": settings.knowledge_domain,
        "chat_model": settings.chat_model,
        "embedding_model": settings.embedding_model,
        "retrieval_k": settings.retrieval_k,
    }
    return config


def flush() -> None:
    """Send whatever is still buffered.

    The SDK batches in the background. A CLI process is short-lived enough to
    exit before that batch leaves, so the traces of the very run you wanted to
    inspect would be the ones lost.
    """
    client = _client()
    if client is None:
        return

    try:
        client.flush()
    except Exception:
        logger.warning("Could not flush traces to Langfuse.", exc_info=True)


def reset() -> None:
    """Drop the cached client. For tests, and for settings changed at runtime."""
    _client.cache_clear()
