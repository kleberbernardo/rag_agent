"""Breaking documents into overlapping, indexable chunks."""

from __future__ import annotations

import logging

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]


def split_documents(
    documents: list[Document],
    *,
    chunk_size: int,
    chunk_overlap: int,
) -> list[Document]:
    """Split documents into chunks that overlap by chunk_overlap characters.

    The overlap keeps an idea whole in at least one chunk when it falls across
    a boundary. An overlap greater than or equal to the chunk size would stop
    the window from advancing, so it is rejected up front.
    """
    if chunk_overlap >= chunk_size:
        msg = (
            f"chunk_overlap ({chunk_overlap}) deve ser menor que "
            f"chunk_size ({chunk_size}), senão a quebra não avança."
        )
        raise ValueError(msg)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=_SEPARATORS,
        length_function=len,
    )
    chunks = splitter.split_documents(documents)

    for index, chunk in enumerate(chunks):
        chunk.metadata["chunk_index"] = index

    logger.info("Split %d document(s) into %d chunk(s)", len(documents), len(chunks))
    return chunks
