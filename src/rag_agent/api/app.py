"""The FastAPI application.

The HTTP layer is a wrapper: it calls the same `agent.service` the CLI calls,
so an endpoint is a translation of request to result and back, never a second
implementation of the agent.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from rag_agent import __version__
from rag_agent.api.routes import router
from rag_agent.api.sessions import SessionStore
from rag_agent.config import get_settings
from rag_agent.indexing import count_documents, describe_location
from rag_agent.logging_setup import setup_logging

logger = logging.getLogger(__name__)

DESCRIPTION = """Agente RAG sobre uma base de documentos própria.

Cada resposta cita o documento de origem e informa o que custou: latência,
tokens e preço estimado.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Report the state of the index at boot, rather than at the first request."""
    setup_logging(verbose=True)
    app.state.sessions = SessionStore()

    try:
        logger.info("Index: %d chunk(s) at %s", count_documents(), describe_location())
    except Exception:
        # A missing vector store is a runtime condition, reported by /health.
        # Refusing to start would take the whole service down for it.
        logger.warning("Vector store unreachable at boot.", exc_info=True)

    yield

    logger.info("Shutting down with %d session(s) open.", len(app.state.sessions))


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
    app.include_router(router)

    logger.info("API ready for domain: %s", settings.knowledge_domain)
    return app


app = create_app()
