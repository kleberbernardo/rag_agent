"""Banco vetorial: guardar pedaços como vetores e buscar por significado.

É aqui que a busca semântica acontece. Texto vira uma lista de 1536 números
(embedding); textos com significado parecido ficam próximos nesse espaço.
"""

from __future__ import annotations

# Para gerar um ID estável a partir do conteúdo do pedaço
import hashlib
import logging

from langchain_chroma import Chroma
from langchain_core.documents import Document
# Embeddings = a classe que converte texto em vetores
from langchain_openai import OpenAIEmbeddings

# get_settings traz a configuração validada do módulo 1
from rag_agent.config import get_settings

logger = logging.getLogger(__name__)


def _build_embeddings() -> OpenAIEmbeddings:
    """Cria o conversor texto -> vetor, usando o modelo definido na config."""
    settings = get_settings()
    return OpenAIEmbeddings(
        # TEM que ser o mesmo modelo na indexação e na busca, senão os vetores não se comparam
        model=settings.embedding_model,
        # O LangChain aceita SecretStr direto e só desembrulha na hora da chamada HTTP
        api_key=settings.openai_api_key,
    )


def get_vector_store() -> Chroma:
    """Abre o banco vetorial em disco (cria se ainda não existir)."""
    settings = get_settings()
    # mkdir cria a pasta | parents=True cria pastas-mãe | exist_ok=True não reclama se já existir
    settings.vector_store_dir.mkdir(parents=True, exist_ok=True)

    return Chroma(
        # Nome da "tabela" dentro do banco: permite vários conjuntos no mesmo arquivo
        collection_name=settings.collection_name,
        # A função que o Chroma vai chamar pra vetorizar tudo que entrar e tudo que for buscado
        embedding_function=_build_embeddings(),
        # Onde gravar em disco. Sem isso, o banco viveria só na memória e sumiria ao fechar
        persist_directory=str(settings.vector_store_dir),
    )


def _stable_id(chunk: Document) -> str:
    """Gera um ID determinístico a partir da fonte + conteúdo do pedaço.

    Serve para tornar a ingestão IDEMPOTENTE: rodar duas vezes sobrescreve
    os mesmos registros em vez de duplicar tudo no índice.
    """
    # Junta a fonte com o texto; a mesma entrada sempre gera a mesma chave
    raw = f"{chunk.metadata.get('source', '')}::{chunk.page_content}"
    # sha256 devolve um resumo de tamanho fixo | encode() transforma str em bytes | hexdigest() vira texto
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def index_documents(chunks: list[Document]) -> int:
    """Vetoriza os pedaços e grava no banco. Devolve quantos foram indexados."""
    # Lista vazia: sair cedo evita uma chamada de API inútil
    if not chunks:
        logger.warning("Nenhum pedaço para indexar.")
        return 0

    store = get_vector_store()
    # Um ID por pedaço, na mesma ordem da lista
    ids = [_stable_id(chunk) for chunk in chunks]

    # Aqui acontece a chamada de rede: todos os textos viram vetores de uma vez
    store.add_documents(documents=chunks, ids=ids)

    logger.info("Indexados %d pedaços em %s", len(chunks), get_settings().vector_store_dir)
    return len(chunks)


def search(query: str, k: int | None = None) -> list[tuple[Document, float]]:
    """Busca os k pedaços mais parecidos com a pergunta.

    Devolve pares (documento, distância). Distância MENOR = mais parecido.
    """
    settings = get_settings()
    # "if k is None" e não "if not k": assim k=0 continua sendo um valor explícito, não vira padrão
    k = settings.retrieval_k if k is None else k

    store = get_vector_store()
    # A pergunta é vetorizada pelo MESMO modelo e comparada com os vetores guardados
    return store.similarity_search_with_score(query, k=k)


def count_documents() -> int:
    """Quantos pedaços estão indexados. Útil para diagnóstico e para os testes."""
    # ._collection acessa o objeto nativo do Chroma por baixo do LangChain
    return get_vector_store()._collection.count()
