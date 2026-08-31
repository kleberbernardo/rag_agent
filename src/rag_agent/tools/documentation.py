"""Semantic search over the indexed knowledge base, exposed as an agent tool.

The description the model reads is built at call time from the configured
knowledge domain, so this tool follows whatever corpus is indexed instead of
naming one in code.
"""

from __future__ import annotations

import logging

from langchain_core.tools import StructuredTool

from rag_agent.config import get_settings
from rag_agent.indexing import search
from rag_agent.prompts import build_search_tool_description
from rag_agent.types import SearchHit

logger = logging.getLogger(__name__)

TOOL_NAME = "search_documentation"

_NO_RESULTS = "Nenhum trecho relevante encontrado na documentação."

_BUDGET_SPENT = (
    "Você já buscou {used} vezes nesta pergunta e não encontrou o assunto. "
    "Pare de buscar. Responda com o que os trechos já trazem, ou diga "
    '"não encontrei isso na documentação".'
)


def search_documentation(question: str) -> str:
    """Retrieve the passages closest in meaning to the question."""
    hits = search(question)

    if not hits:
        return _NO_RESULTS

    logger.info("%s(%r) -> %d hit(s)", TOOL_NAME, question, len(hits))
    return "\n\n".join(_format_hit(position, hit) for position, hit in enumerate(hits, start=1))


def build_search_tool() -> StructuredTool:
    """Build the tool with a description matching the configured domain.

    The tool carries a search budget for the turn it belongs to. A vector
    search always returns its k nearest chunks, however far they sit, so it can
    never report finding nothing; left unchecked the agent rewords the query
    indefinitely on a question the corpus cannot answer, until the graph runs
    out of steps and the call dies with no answer at all. The budget turns that
    into a refusal, which is the truthful outcome.

    The count lives in this closure rather than in a context variable because
    the graph runs tools in a context of its own, where a variable set by one
    call is not visible to the next. A fresh tool per turn is what resets it.
    """
    budget = get_settings().max_searches_per_turn
    used = 0

    def search_with_budget(question: str) -> str:
        nonlocal used
        used += 1

        if used > budget:
            logger.info("Search budget of %d spent; asked %r", budget, question)
            return _BUDGET_SPENT.format(used=budget)

        return search_documentation(question)

    return StructuredTool.from_function(
        func=search_with_budget,
        name=TOOL_NAME,
        description=build_search_tool_description(),
    )


def _format_hit(position: int, hit: SearchHit) -> str:
    """Render one hit with the source label the agent uses to cite it."""
    header = f"--- Trecho {position} [fonte: {hit.citation} | distância {hit.distance:.3f}]"
    return f"{header}\n{hit.content}"
