"""Assembling the agent: model plus tools plus permanent instructions."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent

from rag_agent.prompts import SYSTEM_PROMPT
from rag_agent.providers import build_chat_model
from rag_agent.tools import TOOLS


def build_agent() -> Any:
    """Build the compiled agent graph, ready to invoke.

    A plain RAG pipeline always retrieves once and then answers. This graph
    lets the model decide whether to search, search again with different
    terms, or reach for a different tool entirely.
    """
    return create_agent(
        model=build_chat_model(),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
    )
