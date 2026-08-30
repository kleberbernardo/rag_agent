"""Grading one answer against what the dataset expects.

Every metric here is deterministic: same answer, same score, no second model
involved and no cost. That matters because a grader that is itself a language
model can drift, and a suite you cannot trust is worse than no suite.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from langchain_core.messages import BaseMessage, ToolMessage

from rag_agent.evaluation.dataset import EvalCase
from rag_agent.types import AnswerResult

# The tool renders each retrieved passage with a "[fonte: nome.pdf" label.
_SOURCE_LABEL = re.compile(r"\[fonte:\s*([^\]|]+)")

# What the system prompt tells the agent to say when nothing was found.
_REFUSAL_MARKERS = (
    "nao encontrei",
    "nao consta",
    "nenhum trecho relevante",
)


@dataclass(frozen=True, slots=True)
class CaseScore:
    """How one case did, metric by metric."""

    case_id: str
    question: str
    answer: str
    answerable: bool
    retrieved_sources: list[str]
    retrieval_hit: bool | None
    citation_correct: bool | None
    facts_present: bool | None
    refused: bool
    refusal_correct: bool | None
    latency_seconds: float
    total_tokens: int
    cost_usd: float | None
    error: str | None = None

    @property
    def passed(self) -> bool:
        """A case passes when every metric that applies to it passed."""
        if self.error is not None:
            return False

        applicable = [
            value
            for value in (
                self.retrieval_hit,
                self.citation_correct,
                self.facts_present,
                self.refusal_correct,
            )
            if value is not None
        ]
        return all(applicable)


def score_case(case: EvalCase, result: AnswerResult) -> CaseScore:
    """Grade one answer against its case."""
    answer = result.answer
    sources = extract_retrieved_sources(result.messages)
    refused = is_refusal(answer)

    if case.answerable:
        expected = case.expected_source or ""
        return CaseScore(
            case_id=case.id,
            question=case.question,
            answer=answer,
            answerable=True,
            retrieved_sources=sources,
            retrieval_hit=expected in sources,
            citation_correct=_mentions(answer, expected),
            facts_present=all(_mentions(answer, fact) for fact in case.expected_facts),
            refused=refused,
            refusal_correct=None,
            latency_seconds=_latency(result),
            total_tokens=_tokens(result),
            cost_usd=_cost(result),
        )

    # Outside the corpus: the only thing that matters is that it admitted so.
    return CaseScore(
        case_id=case.id,
        question=case.question,
        answer=answer,
        answerable=False,
        retrieved_sources=sources,
        retrieval_hit=None,
        citation_correct=None,
        facts_present=None,
        refused=refused,
        refusal_correct=refused,
        latency_seconds=_latency(result),
        total_tokens=_tokens(result),
        cost_usd=_cost(result),
    )


def error_score(case: EvalCase, error: Exception) -> CaseScore:
    """Record a case whose run blew up, so one failure cannot end the suite."""
    return CaseScore(
        case_id=case.id,
        question=case.question,
        answer="",
        answerable=case.answerable,
        retrieved_sources=[],
        retrieval_hit=None,
        citation_correct=None,
        facts_present=None,
        refused=False,
        refusal_correct=None,
        latency_seconds=0.0,
        total_tokens=0,
        cost_usd=None,
        error=f"{type(error).__name__}: {error}",
    )


def extract_retrieved_sources(messages: list[BaseMessage]) -> list[str]:
    """Every document the search tool actually returned, in order, deduplicated.

    Read from the tool output rather than by re-running the search, so this
    reflects what the agent really saw -- including a second query with
    different terms.
    """
    found: list[str] = []

    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        for match in _SOURCE_LABEL.findall(str(message.content)):
            source = match.strip()
            if source and source not in found:
                found.append(source)

    return found


def is_refusal(answer: str) -> bool:
    """Whether the answer admits it found nothing."""
    normalised = _normalise(answer)
    return any(marker in normalised for marker in _REFUSAL_MARKERS)


def _mentions(answer: str, needle: str) -> bool:
    return _normalise(needle) in _normalise(answer)


def _normalise(text: str) -> str:
    """Fold case and accents so "não" matches "nao" and "NÃO"."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _latency(result: AnswerResult) -> float:
    return result.metrics.latency_seconds if result.metrics else 0.0


def _tokens(result: AnswerResult) -> int:
    return result.metrics.total_tokens if result.metrics else 0


def _cost(result: AnswerResult) -> float | None:
    return result.metrics.estimated_cost_usd if result.metrics else None
