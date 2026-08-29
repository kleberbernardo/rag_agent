"""Semantic search over the indexed knowledge base, exposed as an agent tool."""

from __future__ import annotations

import logging

from langchain_core.tools import tool

from rag_agent.indexing import search
from rag_agent.types import SearchHit

logger = logging.getLogger(__name__)

_NO_RESULTS = "Nenhum trecho relevante encontrado na documentação."


@tool
def search_documentation(question: str) -> str:
    """Busca trechos relevantes na documentação interna do produto Nimbus.

    Use SEMPRE que a pergunta envolver preços, planos, limites técnicos,
    instalação, configuração ou cancelamento. Não responda sobre esses
    assuntos de memória: consulte aqui primeiro.

    Args:
        question: a pergunta em linguagem natural, com as palavras do usuário.

    Returns:
        Os trechos encontrados, cada um com o nome do arquivo de origem.
    """
    hits = search(question)

    if not hits:
        return _NO_RESULTS

    logger.info("search_documentation(%r) -> %d hit(s)", question, len(hits))
    return "\n\n".join(_format_hit(position, hit) for position, hit in enumerate(hits, start=1))


def _format_hit(position: int, hit: SearchHit) -> str:
    """Render one hit with the source label the agent uses to cite it."""
    header = f"--- Trecho {position} [fonte: {hit.source} | distância {hit.distance:.3f}]"
    return f"{header}\n{hit.content}"
