"""Application service: what the interfaces call, whatever the interface is.

Keeping this layer free of terminal concerns is what makes an HTTP endpoint,
a scheduled job or a bot a thin wrapper instead of a rewrite.
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from rag_agent.agent.builder import build_agent
from rag_agent.types import AnswerResult, ToolCall

logger = logging.getLogger(__name__)


def ask(question: str) -> AnswerResult:
    """Ask a one-off question and return the answer with its reasoning trail."""
    return ChatSession().send(question)


class ChatSession:
    """A conversation that remembers what was already said.

    The model itself is stateless: this accumulated message list *is* the
    memory, resent in full on every turn.
    """

    def __init__(self) -> None:
        self._agent = build_agent()
        self._messages: list[BaseMessage] = []

    @property
    def messages(self) -> list[BaseMessage]:
        return list(self._messages)

    def send(self, question: str) -> AnswerResult:
        """Send a question, updating the conversation history in place."""
        self._messages.append(HumanMessage(question))

        state = self._agent.invoke({"messages": self._messages})
        self._messages = state["messages"]

        result = _to_result(self._messages)
        logger.info("ask(%r) used %d tool(s)", question, len(result.tool_calls))
        return result


def _to_result(messages: list[BaseMessage]) -> AnswerResult:
    """Turn the raw message list into the typed result callers expect."""
    return AnswerResult(
        answer=str(messages[-1].content) if messages else "",
        tool_calls=_extract_tool_calls(messages),
        messages=list(messages),
    )


def _extract_tool_calls(messages: list[BaseMessage]) -> list[ToolCall]:
    return [
        ToolCall(name=call["name"], arguments=call["args"])
        for message in messages
        if isinstance(message, AIMessage) and message.tool_calls
        for call in message.tool_calls
    ]
