"""Domain types shared across layers.

These exist so results travel as typed objects instead of loose dictionaries
that every caller has to unpack and cast by hand.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.documents import Document


@dataclass(frozen=True, slots=True)
class SearchHit:
    """One retrieved chunk and how far it sits from the question."""

    document: Document
    distance: float

    @property
    def source(self) -> str:
        return str(self.document.metadata.get("source", "desconhecida"))

    @property
    def content(self) -> str:
        return self.document.page_content


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A tool the agent decided to invoke, with the arguments it chose."""

    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AnswerResult:
    """The agent's final answer plus the reasoning trail that produced it."""

    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    messages: list[Any] = field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        return [call.name for call in self.tool_calls]

    @property
    def used_tools(self) -> bool:
        return bool(self.tool_calls)
