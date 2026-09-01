"""The FastAPI application.

The HTTP layer is a wrapper: it calls the same `agent.service` the CLI calls,
so an endpoint is a translation of request to result and back, never a second
implementation of the agent.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse

from rag_agent import __version__
from rag_agent.api.feedback import FeedbackStore
from rag_agent.api.routes import router
from rag_agent.api.security import require_api_key
from rag_agent.api.sessions import InMemorySessionStore, RedisSessionStore, SessionStore
from rag_agent.config import SessionBackend, get_settings
from rag_agent.guardrails import GuardrailViolation
from rag_agent.indexing import count_documents, describe_location
from rag_agent.observability import setup_logging

logger = logging.getLogger(__name__)

DESCRIPTION = """Agente RAG sobre uma base de documentos própria.

Cada resposta cita o documento de origem e informa o que custou: latência,
tokens e preço estimado.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Report the state of the index at boot, rather than at the first request."""
    setup_logging(verbose=True)
    app.state.sessions = build_session_store()
    app.state.feedback = FeedbackStore(get_settings().log_dir)

    try:
        logger.info("Index: %d chunk(s) at %s", count_documents(), describe_location())
    except Exception:
        # A missing vector store is a runtime condition, reported by /health.
        # Refusing to start would take the whole service down for it.
        logger.warning("Vector store unreachable at boot.", exc_info=True)

    yield

    logger.info("Shutting down with %d session(s) open.", len(app.state.sessions))


def build_session_store() -> SessionStore:
    """Pick the session backend, falling back when Redis cannot be reached.

    A vanishing Redis should degrade the service to single-replica memory, not
    stop it from answering. The log line says which one is in use.
    """
    settings = get_settings()

    if settings.session_backend is SessionBackend.REDIS:
        try:
            import redis

            client = redis.Redis.from_url(settings.redis_url)
            client.ping()
        except Exception:
            logger.warning(
                "Redis unreachable at %s. Sessions will live in this process only.",
                settings.redis_url,
                exc_info=True,
            )
        else:
            logger.info("Sessions in Redis at %s", settings.redis_url)
            return RedisSessionStore(client, ttl_seconds=settings.session_ttl_seconds)

    logger.info("Sessions in memory, in this process only.")
    return InMemorySessionStore()


def create_app() -> FastAPI:
    """Build the application. A factory, so tests can build their own."""
    settings = get_settings()

    app = FastAPI(
        title="RAG Agent",
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "agent", "description": "Perguntar ao agente."},
            {"name": "ops", "description": "Saúde e configuração."},
        ],
    )
    # Every route is behind the key check. With no key configured it is a
    # no-op, which is what keeps `rag serve` working on a laptop.
    app.include_router(router, dependencies=[Depends(require_api_key)])

    app.add_exception_handler(GuardrailViolation, _refused)

    logger.info("API ready for domain: %s", settings.knowledge_domain)
    return app


async def _refused(request: Request, error: Exception) -> JSONResponse:  # noqa: ARG001
    """Turn a guardrail refusal into 400, not 500.

    The request was understood and rejected on purpose, which is the
    definition of a client error. Returning 500 would page whoever is on call
    for a guardrail doing its job, and would tell the caller to retry
    something that will be refused again.

    The reason travels in its own field so a caller can branch on it without
    parsing Portuguese.
    """
    refusal = error if isinstance(error, GuardrailViolation) else None
    logger.info("Refused a request: %s", refusal.reason if refusal else error)

    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": refusal.detail if refusal else str(error),
            "reason": refusal.reason if refusal else "guardrail",
        },
    )


app = create_app()
