"""Shared fixtures for the whole test suite."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Keep the developer's own environment from leaking into the tests.

    Also clears the settings singleton cache: without it, the first test to
    call get_settings() would freeze its values for every test after it.
    """
    from rag_agent.config import get_settings

    for variable in (
        "OPENAI_API_KEY",
        "CHAT_MODEL",
        "EMBEDDING_MODEL",
        "TEMPERATURE",
        "CHUNK_SIZE",
        "CHUNK_OVERLAP",
        "RETRIEVAL_K",
        "DATA_DIR",
        "VECTOR_STORE_DIR",
        "COLLECTION_NAME",
    ):
        monkeypatch.delenv(variable, raising=False)

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def knowledge_base(tmp_path: Path) -> Path:
    """A minimal knowledge base on disk, one file per subject."""
    root = tmp_path / "data"
    root.mkdir()

    (root / "pricing.md").write_text(
        "# Planos\n\nO plano Growth custa R$ 890 por mes.\n",
        encoding="utf-8",
    )
    (root / "limits.txt").write_text(
        "Tamanho maximo de um evento de log: 256 KB.\n",
        encoding="utf-8",
    )
    (root / "ignored.png").write_bytes(b"\x89PNG\r\n")
    (root / "empty.md").write_text("   \n", encoding="utf-8")

    return root


@pytest.fixture
def temporary_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the vector store at a throwaway directory."""
    index_dir = tmp_path / "chroma"
    monkeypatch.setenv("VECTOR_STORE_DIR", str(index_dir))
    monkeypatch.setenv("COLLECTION_NAME", "test_collection")
    yield index_dir
