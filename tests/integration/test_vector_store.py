"""Vector store round trip. Requires a real OPENAI_API_KEY: embeddings are remote."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from langchain_core.documents import Document

_API_KEY = os.environ.get("OPENAI_API_KEY", "")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _API_KEY, reason="needs a real OPENAI_API_KEY"),
]


@pytest.fixture
def indexed_store(temporary_index: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", _API_KEY)

    from rag_agent.indexing import index_documents

    index_documents(
        [
            Document(
                page_content="O plano Growth custa R$ 890 por mes.",
                metadata={"source": "pricing.md"},
            ),
            Document(
                page_content="Tamanho maximo de um evento de log: 256 KB.",
                metadata={"source": "limits.md"},
            ),
        ]
    )


def test_counts_what_was_indexed(indexed_store: None) -> None:
    from rag_agent.indexing import count_documents

    assert count_documents() == 2


def test_finds_by_meaning_not_by_keyword(indexed_store: None) -> None:
    from rag_agent.indexing import search

    hits = search("qual o preco da assinatura?", k=1)

    assert hits[0].source == "pricing.md"


def test_every_hit_carries_its_source(indexed_store: None) -> None:
    from rag_agent.indexing import search

    assert all(hit.source for hit in search("preco", k=2))


def test_indexing_twice_does_not_duplicate(indexed_store: None) -> None:
    from rag_agent.indexing import count_documents, index_documents

    index_documents(
        [
            Document(
                page_content="O plano Growth custa R$ 890 por mes.",
                metadata={"source": "pricing.md"},
            )
        ]
    )

    assert count_documents() == 2
