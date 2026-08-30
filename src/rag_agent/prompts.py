"""The agent's constitution: behaviour rules, never content.

Written in Brazilian Portuguese on purpose. This text is read by the model,
not by the interpreter, and it is what makes the agent answer in Portuguese.
Each rule exists to prevent a concrete failure observed in RAG systems.

The knowledge domain is interpolated rather than named, so pointing the agent
at a different corpus is a configuration change and not a code change.
"""

from __future__ import annotations

from rag_agent.config import get_settings

SYSTEM_PROMPT_TEMPLATE = """Você é um assistente especializado em {domain}.

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

SEARCH_TOOL_DESCRIPTION_TEMPLATE = """Busca trechos relevantes em {domain}.

Use SEMPRE que a pergunta envolver esse assunto. Não responda sobre ele de
memória: consulte aqui primeiro.

Args:
    question: a pergunta em linguagem natural, com as palavras do usuário.

Returns:
    Os trechos encontrados, cada um com o nome do arquivo de origem."""


def build_system_prompt() -> str:
    """Render the system prompt for the configured knowledge domain."""
    return SYSTEM_PROMPT_TEMPLATE.format(domain=get_settings().knowledge_domain)


def build_search_tool_description() -> str:
    """Render the search tool's description for the configured domain.

    The model never reads the tool's body -- only this text. It is therefore
    the contract that decides whether the tool gets called at all.
    """
    return SEARCH_TOOL_DESCRIPTION_TEMPLATE.format(domain=get_settings().knowledge_domain)
