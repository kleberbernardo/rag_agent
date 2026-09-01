"""What an orchestrator and a load balancer see.

Two probes with different jobs, and a ceiling per caller. None of it changes
an answer, and all of it decides whether answers keep happening.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from rag_agent.api import routes
from rag_agent.api.app import create_app
from rag_agent.config import get_settings
from rag_agent.indexing import DatabaseUnavailableError


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(routes, "count_documents", lambda: 590)

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client


class TestLiveness:
    def test_it_answers_ok(self, client: TestClient) -> None:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_it_stays_up_when_the_database_is_away(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A liveness probe that fails on a dependency causes a restart loop.

        The process is fine. Restarting every replica because the database
        blinked is how one database problem becomes an outage.
        """

        def unreachable() -> int:
            raise DatabaseUnavailableError("Postgres fora do ar")

        monkeypatch.setattr(routes, "count_documents", unreachable)

        with TestClient(create_app(), raise_server_exceptions=False) as client:
            assert client.get("/health").status_code == 200

    def test_it_stays_up_with_an_empty_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(routes, "count_documents", lambda: 0)

        with TestClient(create_app(), raise_server_exceptions=False) as client:
            assert client.get("/health").status_code == 200


class TestReadiness:
    def test_a_working_instance_is_ready(self, client: TestClient) -> None:
        response = client.get("/ready")

        assert response.status_code == 200
        assert response.json()["indexed_chunks"] == 590

    def test_an_unreachable_database_is_not_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """503 takes the instance out of rotation and leaves it running."""

        def unreachable() -> int:
            raise DatabaseUnavailableError("Não foi possível conectar ao Postgres em db:5432.")

        monkeypatch.setattr(routes, "count_documents", unreachable)

        with TestClient(create_app(), raise_server_exceptions=False) as client:
            response = client.get("/ready")

        assert response.status_code == 503
        assert "db:5432" in response.json()["detail"]

    def test_an_empty_index_is_not_ready(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """It answers "não encontrei" to everything, however healthy it is."""
        monkeypatch.setattr(routes, "count_documents", lambda: 0)

        with TestClient(create_app(), raise_server_exceptions=False) as client:
            response = client.get("/ready")

        assert response.status_code == 503
        assert "rag ingest" in response.json()["detail"]

    def test_it_never_leaks_the_password(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://rag:s3cr3t@db:5432/rag")
        get_settings.cache_clear()
        monkeypatch.setattr(routes, "count_documents", lambda: 590)

        with TestClient(create_app(), raise_server_exceptions=False) as client:
            assert "s3cr3t" not in client.get("/ready").text


class TestRateLimit:
    @pytest.fixture
    def limited(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
        monkeypatch.setenv("RATE_LIMIT", "3/minute")
        get_settings.cache_clear()
        monkeypatch.setattr(routes, "count_documents", lambda: 590)
        monkeypatch.setattr(routes, "ask", lambda question: _answer())

        with TestClient(create_app(), raise_server_exceptions=False) as client:
            yield client

    def test_it_refuses_past_the_ceiling(self, limited: TestClient) -> None:
        """One client in a retry loop is one client's problem, not the budget's."""
        codes = [
            limited.post("/ask", json={"question": f"pergunta {n}"}).status_code for n in range(5)
        ]

        assert codes[:3] == [200, 200, 200]
        assert codes[3:] == [429, 429]

    def test_it_says_how_much_is_left(self, limited: TestClient) -> None:
        """A client can slow down before being refused rather than after."""
        response = limited.post("/ask", json={"question": "x"})

        assert "x-ratelimit-remaining" in {name.lower() for name in response.headers}

    def test_the_probes_are_never_limited(self, limited: TestClient) -> None:
        """A balancer polling every two seconds would exhaust the budget alone."""
        codes = {limited.get("/health").status_code for _ in range(10)}

        assert codes == {200}

    def test_readiness_is_not_limited_either(self, limited: TestClient) -> None:
        codes = {limited.get("/ready").status_code for _ in range(10)}

        assert codes == {200}

    def test_an_empty_setting_disables_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`rag serve` on a laptop must not refuse the eleventh question."""
        monkeypatch.setenv("RATE_LIMIT", "")
        get_settings.cache_clear()
        monkeypatch.setattr(routes, "count_documents", lambda: 590)
        monkeypatch.setattr(routes, "ask", lambda question: _answer())

        with TestClient(create_app(), raise_server_exceptions=False) as client:
            codes = {client.post("/ask", json={"question": "x"}).status_code for _ in range(8)}

        assert codes == {200}


class TestCallerIdentity:
    def test_the_key_is_hashed_before_it_is_stored(self) -> None:
        """The identifier reaches the limiter's storage and its error messages."""
        from unittest.mock import Mock

        from rag_agent.api.limits import identify

        request = Mock()
        request.headers = {"X-API-Key": "chave-secreta"}

        identifier = identify(request)

        assert "chave-secreta" not in identifier
        assert identifier.startswith("key:")

    def test_without_a_key_the_address_is_used(self) -> None:
        """A shared key still leaves one client's loop as one client's problem."""
        from unittest.mock import Mock

        from rag_agent.api.limits import identify

        request = Mock()
        request.headers = {}
        request.client.host = "10.0.0.7"

        assert identify(request) == "ip:10.0.0.7"


def _answer() -> object:
    from rag_agent.types import AnswerResult

    return AnswerResult(answer="resposta [fonte: r160.pdf]")
