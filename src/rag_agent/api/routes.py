"""HTTP endpoints.

Thin on purpose. Everything these functions do is call `agent.service` and
shape the result: the same orchestration the CLI uses, with no logic of its
own. That was the point of keeping the service layer free of terminal
concerns.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from rag_agent.agent import ask, format_trace
from rag_agent.api.schemas import (
    AnswerResponse,
    AskRequest,
    ChatRequest,
    HealthResponse,
    StatusResponse,
)
from rag_agent.api.sessions import SessionStore
from rag_agent.config import Settings, get_settings
from rag_agent.evaluation.metrics import extract_retrieved_sources
from rag_agent.indexing import VectorStoreUnavailableError, count_documents, describe_location
from rag_agent.observability import flush

logger = logging.getLogger(__name__)

router = APIRouter()


def get_sessions(request: Request) -> SessionStore:
    """The session store lives on the app, not in a module global."""
    store: SessionStore = request.app.state.sessions
    return store


# Annotated rather than a default value: it keeps the dependency out of the
# function signature's defaults, which is both the current FastAPI style and
# what stops the linter flagging a call in a default argument.
SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionsDep = Annotated[SessionStore, Depends(get_sessions)]


@router.get("/health", response_model=HealthResponse, tags=["ops"])
def health() -> HealthResponse:
    """Liveness, plus whether there is anything to search.

    An empty index answers every question with "não encontrei", so a service
    that reports healthy without saying so is lying by omission.
    """
    try:
        indexed = count_documents()
    except VectorStoreUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error

    return HealthResponse(
        status="ok" if indexed else "empty index",
        indexed_chunks=indexed,
        vector_store=describe_location(),
    )


@router.get("/status", response_model=StatusResponse, tags=["ops"])
def read_status(settings: SettingsDep) -> StatusResponse:
    """The configuration behind the answers, for diagnosing one after the fact."""
    return StatusResponse(
        chat_model=settings.chat_model,
        embedding_model=settings.embedding_model,
        knowledge_domain=settings.knowledge_domain,
        chunk_strategy=settings.chunk_strategy.value,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        retrieval_k=settings.retrieval_k,
        vector_store=describe_location(),
        indexed_chunks=_safe_count(),
        tracing_enabled=settings.tracing_enabled,
    )


@router.post("/ask", response_model=AnswerResponse, tags=["agent"])
def ask_once(payload: AskRequest) -> AnswerResponse:
    """Answer one question, with no memory of anything before it."""
    _require_index()

    result = ask(payload.question)
    flush()

    return AnswerResponse.from_result(
        result,
        sources=extract_retrieved_sources(result.messages),
        trace=format_trace(result.messages) if payload.trace else None,
    )


@router.post("/chat", response_model=AnswerResponse, tags=["agent"])
def chat(payload: ChatRequest, sessions: SessionsDep) -> AnswerResponse:
    """Answer inside a conversation, remembering the earlier turns.

    Omit session_id to start one; send back the id from the response to
    continue it.
    """
    _require_index()

    session_id, session = sessions.get_or_create(payload.session_id)
    result = session.send(payload.question)
    flush()

    return AnswerResponse.from_result(
        result,
        sources=extract_retrieved_sources(result.messages),
        session_id=session_id,
        trace=format_trace(result.messages) if payload.trace else None,
    )


@router.delete("/chat/{session_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["agent"])
def end_chat(session_id: str, sessions: SessionsDep) -> None:
    """Forget a conversation."""
    if not sessions.drop(session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sessão não encontrada.")


def _require_index() -> None:
    """Refuse to answer against an empty index instead of answering uselessly."""
    if _safe_count() == 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="O índice está vazio. Rode a ingestão antes de perguntar.",
        )


def _safe_count() -> int:
    try:
        return count_documents()
    except VectorStoreUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
