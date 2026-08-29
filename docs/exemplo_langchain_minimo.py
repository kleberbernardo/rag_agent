"""Menor programa possível com LangChain: mandar uma pergunta e imprimir a resposta."""

import sys

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

sys.stdout.reconfigure(encoding="utf-8")  # evita acento quebrado no console do Windows

# 1. O modelo. Lê OPENAI_API_KEY do ambiente sozinho.
llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)

# 2. A conversa é uma LISTA de mensagens, cada uma com um papel.
mensagens = [
    SystemMessage("Você é um assistente técnico. Responda em no máximo 2 frases."),
    HumanMessage("O que é RAG em inteligência artificial?"),
]

# 3. invoke() = manda e espera a resposta completa.
resposta = llm.invoke(mensagens)

print("RESPOSTA:", resposta.content)
print("\nTIPO:", type(resposta).__name__)
print("TOKENS:", resposta.usage_metadata)
