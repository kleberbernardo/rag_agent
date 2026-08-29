"""O agente: junta modelo + ferramentas + instruções e roda o loop de decisão.

Diferença entre RAG simples e agente:
  RAG simples -> SEMPRE busca uma vez, depois responde.
  Agente      -> DECIDE se busca, pode buscar de novo com outros termos,
                 pode usar duas ferramentas na mesma pergunta.
"""

from __future__ import annotations

import logging

# create_agent monta o grafo pronto: modelo -> decide -> executa tool -> volta
from langchain.agents import create_agent
# Os tipos de mensagem que compõem a conversa
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI

from rag_agent.config import get_settings
from rag_agent.tools import FERRAMENTAS

logger = logging.getLogger(__name__)

# O system prompt é a "constituição" do agente: define comportamento, não conteúdo.
# Cada regra aqui existe para evitar uma falha concreta observada em RAG.
SYSTEM_PROMPT = """Você é o assistente da documentação do produto Nimbus.

Regras:
1. Para QUALQUER pergunta sobre o produto (preços, planos, limites, instalação,
   configuração, cancelamento), use a ferramenta buscar_documentacao ANTES de
   responder. Nunca responda sobre o produto de memória.
2. Responda APENAS com o que estiver nos trechos recuperados. Se a informação
   não estiver lá, diga "não encontrei isso na documentação" -- não invente.
3. Sempre cite a fonte no final, no formato: (fonte: arquivo.md)
4. Para qualquer conta aritmética, use a ferramenta calcular. Não faça contas
   de cabeça.
5. Seja direto. Responda em português do Brasil."""


def build_agent():
    """Monta o agente. Devolve um grafo LangGraph compilado, pronto para invoke()."""
    settings = get_settings()

    # O modelo ainda não faz nada aqui: é só configuração guardada
    modelo = ChatOpenAI(
        model=settings.chat_model,
        # 0 = determinístico. Para RAG queremos fidelidade ao documento, não criatividade
        temperature=settings.temperature,
        api_key=settings.openai_api_key,
    )

    # create_agent constrói o loop: pensar -> chamar tool -> ler resultado -> pensar de novo
    return create_agent(
        model=modelo,
        # A lista de ferramentas do módulo 4. O modelo recebe a descrição de cada uma
        tools=FERRAMENTAS,
        # As instruções permanentes, injetadas em toda chamada
        system_prompt=SYSTEM_PROMPT,
    )


def perguntar(pergunta: str) -> dict[str, object]:
    """Faz uma pergunta ao agente e devolve a resposta junto com o rastro do raciocínio.

    Returns:
        dict com 'resposta' (texto final), 'ferramentas' (quais foram chamadas)
        e 'mensagens' (a conversa completa, para depuração).
    """
    agente = build_agent()

    # O estado do agente é um dicionário; "messages" é a lista da conversa.
    # invoke() roda o loop INTEIRO e só volta quando o modelo para de chamar ferramentas
    estado = agente.invoke({"messages": [HumanMessage(pergunta)]})

    # A conversa final inclui: sua pergunta, os pedidos de ferramenta, os
    # resultados das ferramentas, e a resposta final
    mensagens: list[BaseMessage] = estado["messages"]

    chamadas: list[dict[str, object]] = []
    for msg in mensagens:
        # tool_calls só existe em AIMessage, e só quando o modelo pediu uma ferramenta
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for chamada in msg.tool_calls:
                chamadas.append({"nome": chamada["name"], "argumentos": chamada["args"]})

    # A última mensagem é sempre a resposta final em texto
    resposta = mensagens[-1].content

    logger.info("perguntar(%r) usou %d ferramenta(s)", pergunta, len(chamadas))
    return {"resposta": resposta, "ferramentas": chamadas, "mensagens": mensagens}


def formatar_rastro(mensagens: list[BaseMessage]) -> str:
    """Transforma a conversa interna em texto legível, para você ver o agente pensando."""
    linhas: list[str] = []
    for msg in mensagens:
        if isinstance(msg, HumanMessage):
            linhas.append(f"[VOCÊ] {msg.content}")
        elif isinstance(msg, AIMessage) and msg.tool_calls:
            for c in msg.tool_calls:
                linhas.append(f"[AGENTE decide] chamar {c['name']}({c['args']})")
        elif isinstance(msg, ToolMessage):
            # A ferramenta pode devolver muito texto; cortar mantém o rastro legível
            preview = msg.content[:100].replace("\n", " ")
            linhas.append(f"[FERRAMENTA {msg.name}] -> {preview}...")
        elif isinstance(msg, AIMessage) and msg.content:
            linhas.append(f"[AGENTE responde] {msg.content}")
    return "\n".join(linhas)
