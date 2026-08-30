"""The HTTP layer. It must translate, never decide.

The agent is faked throughout: what is under test is the wrapper, not the
model. A test that spends tokens is a test nobody runs.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, ToolMessage

from rag_agent.api import create_app
from rag_agent.api.sessions import SessionStore
from rag_agent.types import AnswerResult, RunMetrics, ToolCall

SOURCE = "cvm-resolucao-160-ofertas-publicas.pdf"


def build_result(text: str = "O limite é 15%.") -> AnswerResult:
    return AnswerResult(
        answer=text,
        tool_calls=[ToolCall(name="search_documentation", arguments={"question": "limite"})],
        messages=[
            ToolMessage(
                content=f"--- Trecho 1 [fonte: {SOURCE}, Art. 60 | distância 0.4]\nconteúdo",
                tool_call_id="1",
                name="search_documentation",
            ),
            AIMessage(content=text),
        ],
        metrics=RunMetrics(
            latency_seconds=1.5,
            input_tokens=100,
            output_tokens=20,
            tool_calls=1,
            model="gpt-4o-mini",
            estimated_cost_usd=0.00003,
        ),
    )


class FakeSession:
    def __init__(self) -> None:
        self.questions: list[str] = []

    def send(self, question: str) -> AnswerResult:
        self.questions.append(question)
        return build_result(f"resposta {len(self.questions)}")


@pytest.fixture
def indexed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A store that answers, so endpoints are not blocked by an empty index."""
    from rag_agent.api import routes

    monkeypatch.setattr(routes, "count_documents", lambda: 590)
    monkeypatch.setattr(routes, "describe_location", lambda: "/app/.chroma")
    monkeypatch.setattr(routes, "ask", lambda question: build_result())
    monkeypatch.setattr(routes, "flush", lambda: None)


@pytest.fixture
def empty_index(monkeypatch: pytest.MonkeyPatch) -> None:
    from rag_agent.api import routes

    monkeypatch.setattr(routes, "count_documents", lambda: 0)
    monkeypatch.setattr(routes, "describe_location", lambda: "/app/.chroma")


@pytest.fixture
def client(indexed: None) -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app) as test_client:
        # Replace the store built at startup with one that fakes the agent.
        test_client.app.state.sessions = SessionStore(factory=FakeSession)  # type: ignore[attr-defined,arg-type]
        yield test_client


class TestHealth:
    def test_reports_ok_with_a_populated_index(self, client: TestClient) -> None:
        body = client.get("/health").json()

        assert body["status"] == "ok"
        assert body["indexed_chunks"] == 590

    def test_says_so_when_the_index_is_empty(self, empty_index: None) -> None:
        """A healthy service over an empty index would be lying by omission."""
        with TestClient(create_app()) as unindexed:
            body = unindexed.get("/health").json()

        assert body["status"] == "empty index"
        assert body["indexed_chunks"] == 0

    def test_reports_503_when_the_store_is_unreachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from rag_agent.api import routes
        from rag_agent.indexing import VectorStoreUnavailableError

        def unreachable() -> int:
            msg = "Não foi possível conectar ao Chroma em chroma:8000."
            raise VectorStoreUnavailableError(msg)

        monkeypatch.setattr(routes, "count_documents", unreachable)

        with TestClient(create_app(), raise_server_exceptions=False) as broken:
            response = broken.get("/health")

        assert response.status_code == 503
        assert "chroma:8000" in response.json()["detail"]


class TestStatus:
    def test_exposes_the_active_configuration(self, client: TestClient) -> None:
        body = client.get("/status").json()

        assert body["chat_model"]
        assert body["chunk_strategy"] in {"characters", "articles"}
        assert body["retrieval_k"] > 0


class TestAsk:
    def test_answers_a_question(self, client: TestClient) -> None:
        body = client.post("/ask", json={"question": "qual o limite?"}).json()

        assert body["answer"] == "O limite é 15%."

    def test_reports_the_sources_it_retrieved(self, client: TestClient) -> None:
        body = client.post("/ask", json={"question": "qual o limite?"}).json()

        assert body["sources"] == [SOURCE]

    def test_reports_the_tools_and_the_cost(self, client: TestClient) -> None:
        body = client.post("/ask", json={"question": "qual o limite?"}).json()

        assert body["tools_used"][0]["name"] == "search_documentation"
        assert body["metrics"]["total_tokens"] == 120
        assert body["metrics"]["estimated_cost_usd"] == 0.00003

    def test_omits_the_trace_unless_asked(self, client: TestClient) -> None:
        body = client.post("/ask", json={"question": "q"}).json()

        assert body["trace"] is None

    def test_includes_the_trace_on_request(self, client: TestClient) -> None:
        body = client.post("/ask", json={"question": "q", "trace": True}).json()

        assert body["trace"] is not None
        assert "search_documentation" in body["trace"]

    def test_a_single_question_carries_no_session(self, client: TestClient) -> None:
        assert client.post("/ask", json={"question": "q"}).json()["session_id"] is None

    @pytest.mark.parametrize("payload", [{}, {"question": ""}, {"question": "x" * 2001}])
    def test_rejects_an_invalid_body(self, client: TestClient, payload: dict[str, Any]) -> None:
        assert client.post("/ask", json=payload).status_code == 422

    def test_refuses_to_answer_against_an_empty_index(self, empty_index: None) -> None:
        with TestClient(create_app()) as unindexed:
            response = unindexed.post("/ask", json={"question": "q"})

        assert response.status_code == 503
        assert "índice está vazio" in response.json()["detail"]


class TestChat:
    def test_opens_a_session_when_none_is_given(self, client: TestClient) -> None:
        body = client.post("/chat", json={"question": "primeira"}).json()

        assert body["session_id"]

    def test_the_same_session_keeps_talking_to_the_same_conversation(
        self, client: TestClient
    ) -> None:
        first = client.post("/chat", json={"question": "primeira"}).json()
        second = client.post(
            "/chat", json={"question": "segunda", "session_id": first["session_id"]}
        ).json()

        assert second["session_id"] == first["session_id"]

    def test_different_calls_without_an_id_get_different_sessions(self, client: TestClient) -> None:
        first = client.post("/chat", json={"question": "a"}).json()
        second = client.post("/chat", json={"question": "b"}).json()

        assert first["session_id"] != second["session_id"]

    def test_a_session_can_be_ended(self, client: TestClient) -> None:
        session_id = client.post("/chat", json={"question": "a"}).json()["session_id"]

        assert client.delete(f"/chat/{session_id}").status_code == 204

    def test_ending_an_unknown_session_is_a_404(self, client: TestClient) -> None:
        assert client.delete("/chat/nao-existe").status_code == 404


class TestSessionStore:
    def test_an_unknown_id_opens_a_new_conversation(self) -> None:
        """A client holding an id from before a restart should keep working."""
        store = SessionStore(factory=FakeSession)  # type: ignore[arg-type]

        returned_id, _ = store.get_or_create("id-de-antes-do-restart")

        assert returned_id == "id-de-antes-do-restart"
        assert len(store) == 1

    def test_the_same_id_returns_the_same_conversation(self) -> None:
        store = SessionStore(factory=FakeSession)  # type: ignore[arg-type]
        _, first = store.get_or_create("s1")
        _, second = store.get_or_create("s1")

        assert first is second

    def test_the_oldest_session_is_evicted_at_the_cap(self) -> None:
        """Unbounded session storage is a memory leak with a friendly name."""
        store = SessionStore(max_sessions=2, factory=FakeSession)  # type: ignore[arg-type]
        store.get_or_create("a")
        store.get_or_create("b")
        store.get_or_create("c")

        assert len(store) == 2
        assert store.drop("a") is False
        assert store.drop("c") is True

    def test_using_a_session_keeps_it_from_being_evicted(self) -> None:
        store = SessionStore(max_sessions=2, factory=FakeSession)  # type: ignore[arg-type]
        store.get_or_create("a")
        store.get_or_create("b")
        store.get_or_create("a")
        store.get_or_create("c")

        assert store.drop("a") is True
        assert store.drop("b") is False
