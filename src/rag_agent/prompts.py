"""The agent's constitution: behaviour rules, never content.

Written in Brazilian Portuguese on purpose. This text is read by the model,
not by the interpreter, and it is what makes the agent answer in Portuguese.
Each rule exists to prevent a concrete failure observed in RAG systems.

The prompt is fetched from Langfuse when tracing is configured, so changing how
the agent behaves becomes a label change in a UI rather than a commit, a build
and a deploy. The text below is the fallback and the source of what gets
published: an unreachable Langfuse must never stop the agent from answering.

Placeholders use the `{{name}}` form because that is what Langfuse compiles.
One syntax on both paths means the template is published verbatim.
"""

from __future__ import annotations

import logging

from rag_agent.config import get_settings
from rag_agent.observability import fetch_prompt

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_NAME = "rag-agent-system"
SEARCH_TOOL_PROMPT_NAME = "rag-agent-search-tool"

SYSTEM_PROMPT_TEMPLATE = """Você é um assistente especializado em {{domain}}.

Regras:
1. Para QUALQUER pergunta sobre o assunto, use a ferramenta
   search_documentation ANTES de responder. Nunca responda de memória.
2. Responda APENAS com o que estiver nos trechos recuperados. Se a informação
   não estiver lá, diga "não encontrei isso na documentação" -- não invente.
3. Se a primeira busca não trouxer o que você precisa, tente NO MÁXIMO mais
   uma vez, com outros termos. Se ainda assim não achar, responda "não
   encontrei isso na documentação". Não fique buscando indefinidamente.
4. Sempre cite a fonte no final, no formato: (fonte: arquivo.md)
5. Para qualquer conta aritmética, use a ferramenta calculate. Não faça contas
   de cabeça.
6. Seja direto. Responda em português do Brasil."""

SEARCH_TOOL_DESCRIPTION_TEMPLATE = """Busca trechos relevantes em {{domain}}.

Use SEMPRE que a pergunta envolver esse assunto. Não responda sobre ele de
memória: consulte aqui primeiro.

Args:
    question: a pergunta em linguagem natural, com as palavras do usuário.

Returns:
    Os trechos encontrados, cada um com o nome do arquivo de origem."""

PUBLISHED_PROMPTS = {
    SYSTEM_PROMPT_NAME: SYSTEM_PROMPT_TEMPLATE,
    SEARCH_TOOL_PROMPT_NAME: SEARCH_TOOL_DESCRIPTION_TEMPLATE,
}


def build_system_prompt() -> str:
    """Render the system prompt for the configured knowledge domain."""
    return _render(SYSTEM_PROMPT_NAME, SYSTEM_PROMPT_TEMPLATE)


def build_search_tool_description() -> str:
    """Render the search tool's description for the configured domain.

    The model never reads the tool's body, only this text. It is therefore the
    contract that decides whether the tool gets called at all.
    """
    return _render(SEARCH_TOOL_PROMPT_NAME, SEARCH_TOOL_DESCRIPTION_TEMPLATE)


def describe_source() -> tuple[str, int | None]:
    """Where the active system prompt came from, and which version.

    Recorded next to an evaluation score, because a run graded against one
    prompt version cannot be compared to a run graded against another.
    """
    _, version = fetch_prompt(
        SYSTEM_PROMPT_NAME,
        label=get_settings().prompt_label,
        fallback=SYSTEM_PROMPT_TEMPLATE,
    )
    return ("langfuse" if version is not None else "local", version)


def _render(name: str, fallback: str) -> str:
    settings = get_settings()
    template, _ = fetch_prompt(name, label=settings.prompt_label, fallback=fallback)

    return template.replace("{{domain}}", settings.knowledge_domain)
