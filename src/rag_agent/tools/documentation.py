"""Semantic search over the indexed knowledge base, exposed as an agent tool.

The description the model reads is built at call time from the configured
knowledge domain, so this tool follows whatever corpus is indexed instead of
naming one in code.
"""

from __future__ import annotations

import logging

from langchain_core.tools import StructuredTool

from rag_agent.indexing import search
from rag_agent.prompts import build_search_tool_description
from rag_agent.types import SearchHit

logger = logging.getLogger(__name__)

TOOL_NAME = "search_documentation"

_NO_RESULTS = "Nenhum trecho relevante encontrado na documentação."


def search_documentation(question: str) -> str:
    """Retrieve the passages closest in meaning to the question."""
    hits = search(question)

    if not hits:
        return _NO_RESULTS

    logger.info("%s(%r) -> %d hit(s)", TOOL_NAME, question, len(hits))
    return "\n\n".join(_format_hit(position, hit) for position, hit in enumerate(hits, start=1))


def build_search_tool() -> StructuredTool:
    """Build the tool with a description matching the configured domain."""
    return StructuredTool.from_function(
        func=search_documentation,
        name=TOOL_NAME,
        description=build_search_tool_description(),
    )


def _format_hit(position: int, hit: SearchHit) -> str:
    """Render one hit with the source label the agent uses to cite it."""
    header = f"--- Trecho {position} [fonte: {hit.source} | distância {hit.distance:.3f}]"
    return f"{header}\n{hit.content}"
