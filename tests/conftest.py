"""Shared fixtures for the whole test suite."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Keep the developer's own environment from leaking into the tests.

    Three separate leaks are closed here:

    * the environment variables themselves;
    * the .env file, which pydantic-settings reads from the working directory
      regardless of what the environment says -- so the tests run somewhere
      that has none;
    * the settings singleton cache, which would otherwise let the first test
      to call get_settings() freeze its values for every test after it.
    """
    from rag_agent.config import get_settings

    monkeypatch.chdir(tmp_path)

    for variable in (
        "OPENAI_API_KEY",
        "CHAT_MODEL",
        "EMBEDDING_MODEL",
        "TEMPERATURE",
        "CHUNK_SIZE",
        "CHUNK_OVERLAP",
        "CHUNK_STRATEGY",
        "ARTICLE_MAX_CHARS",
        "RETRIEVAL_K",
        "SEARCH_STRATEGY",
        "MAX_SEARCHES_PER_TURN",
        "DATA_DIR",
        "COLLECTION_NAME",
        "DATABASE_URL",
        "DATABASE_POOL_SIZE",
        "DATABASE_MAX_OVERFLOW",
        "EMBEDDING_DIMENSIONS",
        "KNOWLEDGE_DOMAIN",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
        "PROMPT_LABEL",
        "PROMPT_CACHE_SECONDS",
        "LANGSMITH_TRACING",
        "LANGSMITH_API_KEY",
        "SESSION_BACKEND",
        "REDIS_URL",
        "SESSION_TTL_SECONDS",
        "API_KEY",
        "MAX_RETRIES",
        "REQUEST_TIMEOUT_SECONDS",
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


def postgres_is_up() -> bool:
    """Whether the test database is reachable.

    The store no longer has an embedded mode, so anything that touches it
    needs a running Postgres. Tests that do are skipped rather than failed
    when there is none, which keeps the unit suite runnable with no
    infrastructure at all.
    """
    from sqlalchemy import create_engine, text

    from rag_agent.config import Settings

    try:
        engine = create_engine(Settings().database_url, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
    except Exception:
        return False
    return True


requires_postgres = pytest.mark.skipif(
    not postgres_is_up(),
    reason="needs a running Postgres (docker compose up -d postgres)",
)


@pytest.fixture
def temporary_index(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Point the vector store at a throwaway collection.

    A collection per test rather than a database per test: the rows are
    scoped by collection anyway, and creating one costs a single insert
    against a database that is already up.
    """
    from rag_agent.config import get_settings
    from rag_agent.indexing import forget_engine

    name = f"test_{uuid4().hex}"
    monkeypatch.setenv("COLLECTION_NAME", name)
    get_settings.cache_clear()
    forget_engine()

    yield name

    from rag_agent.indexing import reset_index

    with suppress(Exception):
        reset_index()
    forget_engine()
