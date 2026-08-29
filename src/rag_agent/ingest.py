"""Fase offline: ler arquivos do disco e quebrá-los em pedaços indexáveis.

Fluxo: carregar -> quebrar. Duas funções puras, sem rede, testáveis de graça.
"""

# Faz anotações de tipo serem lidas como texto: permite escrever list[Document] em versões antigas
from __future__ import annotations

# Módulo padrão de logs. Melhor que print(): dá pra ligar/desligar por nível
import logging

# Path = caminho de arquivo como objeto
from pathlib import Path

# Document = a estrutura central do LangChain: texto + metadados
from langchain_core.documents import Document

# O splitter que corta tentando respeitar parágrafo, linha e palavra, nessa ordem
from langchain_text_splitters import RecursiveCharacterTextSplitter

# __name__ vira "rag_agent.ingest": permite filtrar logs por módulo
logger = logging.getLogger(__name__)

# Extensões de texto puro que sabemos ler
TEXT_SUFFIXES = {".md", ".txt", ".markdown", ".rst"}
# Extensões que precisam de extração especial
PDF_SUFFIXES = {".pdf"}
# O "|" entre conjuntos é união: junta os dois numa lista só de extensões aceitas
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | PDF_SUFFIXES


# "_" no início = função privada deste módulo, não faz parte da API pública
def _load_text_file(path: Path) -> list[Document]:
    """Lê um arquivo de texto e devolve um único Document."""
    # errors="ignore": um byte mal codificado não pode derrubar a ingestão inteira
    content = path.read_text(encoding="utf-8", errors="ignore")
    # .strip() remove espaços/quebras; se sobrou nada, o arquivo é vazio
    if not content.strip():
        # Devolve lista vazia em vez de None: quem chama sempre pode fazer extend()
        return []
    # metadata["source"] é o que vai permitir a resposta final CITAR a fonte
    return [Document(page_content=content, metadata={"source": path.name})]


def _load_pdf_file(path: Path) -> list[Document]:
    """Lê um PDF e devolve UM Document POR PÁGINA."""
    # Import aqui dentro (não no topo): só carrega o pypdf se realmente houver PDF
    from pypdf import PdfReader

    # PdfReader espera string, não Path
    reader = PdfReader(str(path))
    # Lista vazia que vamos preenchendo página a página
    docs: list[Document] = []
    # enumerate(..., start=1) numera a partir de 1, como humano conta página
    for page_number, page in enumerate(reader.pages, start=1):
        # extract_text() devolve None em página sem texto; "or ''" evita erro adiante
        text = page.extract_text() or ""
        # Página só de imagem (PDF escaneado) não tem texto: pular, senão polui o índice
        if not text.strip():
            continue
        # Guardar a página no metadado permite responder "manual.pdf, página 12"
        docs.append(
            Document(page_content=text, metadata={"source": path.name, "page": page_number})
        )
    return docs


def load_documents(data_dir: Path) -> list[Document]:
    """Varre a pasta recursivamente e carrega todo arquivo suportado."""
    # Pasta errada é quase sempre erro de configuração: falhar cedo e alto
    if not data_dir.exists():
        msg = f"Pasta de dados não encontrada: {data_dir}"
        raise FileNotFoundError(msg)

    documents: list[Document] = []
    # rglob("*") = varre recursivamente | sorted() garante MESMA ORDEM em toda execução
    for path in sorted(data_dir.rglob("*")):
        # rglob também devolve pastas; queremos só arquivos
        if not path.is_file():
            continue
        # .lower() para aceitar "ARQUIVO.MD" igual a "arquivo.md"
        suffix = path.suffix.lower()
        # Extensão desconhecida é IGNORADA, não é erro: toda pasta tem lixo (.DS_Store, imagens)
        if suffix not in SUPPORTED_SUFFIXES:
            continue

        # Escolhe o leitor certo pelo tipo de arquivo
        if suffix in PDF_SUFFIXES:
            loaded = _load_pdf_file(path)
        else:
            loaded = _load_text_file(path)

        # debug = só aparece se você ligar o log detalhado
        logger.debug("Carregado %s (%d documento(s))", path.name, len(loaded))
        # extend() adiciona todos os itens da lista; append() adicionaria a lista inteira como 1 item
        documents.extend(loaded)

    logger.info("Carregados %d documento(s) de %s", len(documents), data_dir)
    return documents


# O "*" sozinho obriga os parâmetros seguintes a serem passados por NOME
def split_documents(
    documents: list[Document],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Document]:
    """Quebra documentos em pedaços com sobreposição."""
    # Overlap >= chunk faz a janela nunca avançar: pedaços duplicados ou loop infinito
    if chunk_overlap >= chunk_size:
        msg = (
            f"chunk_overlap ({chunk_overlap}) deve ser menor que "
            f"chunk_size ({chunk_size}), senão a quebra não avança."
        )
        raise ValueError(msg)

    splitter = RecursiveCharacterTextSplitter(
        # Teto de caracteres por pedaço (não é alvo: ele prefere cortar antes, num lugar melhor)
        chunk_size=chunk_size,
        # Caracteres repetidos entre pedaços vizinhos
        chunk_overlap=chunk_overlap,
        # ORDEM DE PRIORIDADE dos cortes: parágrafo -> linha -> frase -> palavra -> caractere
        separators=["\n\n", "\n", ". ", " ", ""],
        # Como medir "tamanho". len = caracteres. Poderia ser um contador de tokens
        length_function=len,
    )
    # split_documents propaga os metadados do original para cada pedaço gerado
    chunks = splitter.split_documents(documents)

    # enumerate numera os pedaços na ordem: serve pra depurar e pra deduplicar depois
    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index

    logger.info("Gerados %d pedaços de %d documento(s)", len(chunks), len(documents))
    return chunks
