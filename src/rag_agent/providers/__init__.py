"""LLM and embedding clients, isolated from the rest of the application.

Every OpenAI import lives behind this package. Swapping providers means
touching these modules and nothing else.
"""

from rag_agent.providers.chat_model import build_chat_model
from rag_agent.providers.embeddings import build_embeddings

__all__ = ["build_chat_model", "build_embeddings"]
