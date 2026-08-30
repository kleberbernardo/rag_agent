"""Vector store deployment modes: embedded on disk, or a standalone server.

Both modes must expose the same interface, and choosing between them must be
a configuration change — never a code change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rag_agent.config import VectorStoreMode, get_settings
from rag_agent.indexing import VectorStoreUnavailableError, describe_location
from rag_agent.indexing import vector_store as module


class FakeChromaClient:
    """Stands in for chromadb.HttpClient without opening a socket."""

    def __init__(self, *, reachable: bool = True) -> None:
        self.reachable = reachable
        self.heartbeats = 0

    def heartbeat(self) -> int:
        self.heartbeats += 1
        if not self.reachable:
            msg = "connection refused"
            raise ConnectionError(msg)
        return 1


@pytest.fixture
def server_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VECTOR_STORE_MODE", "server")
    monkeypatch.setenv("CHROMA_HOST", "chroma.internal")
    monkeypatch.setenv("CHROMA_PORT", "9000")
    get_settings.cache_clear()


@pytest.fixture
def captured_chroma(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Record how Chroma was constructed instead of constructing it."""
    captured: dict[str, Any] = {}

    def fake_chroma(**kwargs: Any) -> str:
        captured.update(kwargs)
        return "store"

    monkeypatch.setattr(module, "Chroma", fake_chroma)
    monkeypatch.setattr(module, "build_embeddings", lambda: "embeddings")
    return captured


class TestModeSelection:
    def test_defaults_to_embedded(self) -> None:
        assert get_settings().vector_store_mode is VectorStoreMode.EMBEDDED

    def test_embedded_writes_to_a_directory(
        self, captured_chroma: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VECTOR_STORE_DIR", str(tmp_path / "index"))
        get_settings.cache_clear()

        module.get_vector_store()

        assert captured_chroma["persist_directory"] == str(tmp_path / "index")
        assert "client" not in captured_chroma

    def test_embedded_creates_the_directory(
        self, captured_chroma: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "nested" / "index"
        monkeypatch.setenv("VECTOR_STORE_DIR", str(target))
        get_settings.cache_clear()

        module.get_vector_store()

        assert target.is_dir()

    def test_server_passes_a_client_instead_of_a_directory(
        self, server_mode: None, captured_chroma: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("chromadb.HttpClient", lambda **_: FakeChromaClient())

        module.get_vector_store()

        assert "client" in captured_chroma
        assert "persist_directory" not in captured_chroma

    def test_server_uses_the_configured_address(
        self, server_mode: None, captured_chroma: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, Any] = {}

        def fake_http_client(**kwargs: Any) -> FakeChromaClient:
            seen.update(kwargs)
            return FakeChromaClient()

        monkeypatch.setattr("chromadb.HttpClient", fake_http_client)

        module.get_vector_store()

        assert seen == {"host": "chroma.internal", "port": 9000}

    def test_both_modes_keep_the_same_collection(
        self, captured_chroma: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module.get_vector_store()
        embedded_collection = captured_chroma["collection_name"]

        monkeypatch.setenv("VECTOR_STORE_MODE", "server")
        monkeypatch.setattr("chromadb.HttpClient", lambda **_: FakeChromaClient())
        get_settings.cache_clear()

        module.get_vector_store()

        assert captured_chroma["collection_name"] == embedded_collection


class TestUnreachableServer:
    def test_raises_a_typed_error(
        self, server_mode: None, captured_chroma: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("chromadb.HttpClient", lambda **_: FakeChromaClient(reachable=False))

        with pytest.raises(VectorStoreUnavailableError):
            module.get_vector_store()

    def test_the_message_names_the_address_and_the_way_out(
        self, server_mode: None, captured_chroma: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("chromadb.HttpClient", lambda **_: FakeChromaClient(reachable=False))

        with pytest.raises(VectorStoreUnavailableError) as raised:
            module.get_vector_store()

        message = str(raised.value)
        assert "chroma.internal:9000" in message
        assert "docker compose" in message
        assert "embedded" in message

    def test_the_original_failure_is_preserved(
        self, server_mode: None, captured_chroma: dict[str, Any], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("chromadb.HttpClient", lambda **_: FakeChromaClient(reachable=False))

        with pytest.raises(VectorStoreUnavailableError) as raised:
            module.get_vector_store()

        assert isinstance(raised.value.__cause__, ConnectionError)


class TestDescribeLocation:
    def test_embedded_shows_the_path(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VECTOR_STORE_DIR", str(tmp_path / "index"))
        get_settings.cache_clear()

        assert describe_location() == str(tmp_path / "index")

    def test_server_shows_the_address(self, server_mode: None) -> None:
        assert describe_location() == "chroma://chroma.internal:9000"
