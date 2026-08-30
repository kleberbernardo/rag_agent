"""Measuring the agent against questions whose answers are known.

Unit tests prove the code does what it was written to do. This proves the
system answers correctly -- a different question, and the one that decides
whether a change to the prompt, the chunking or the model made things better
or worse.
"""

from rag_agent.evaluation.dataset import DEFAULT_DATASET, EvalCase, load_dataset
from rag_agent.evaluation.metrics import (
    CaseScore,
    error_score,
    extract_retrieved_sources,
    groundedness,
    is_refusal,
    score_case,
)
from rag_agent.evaluation.runner import EvalReport, Rate, build_report, run_evaluation, save_report

__all__ = [
    "DEFAULT_DATASET",
    "CaseScore",
    "EvalCase",
    "EvalReport",
    "Rate",
    "build_report",
    "error_score",
    "extract_retrieved_sources",
    "groundedness",
    "is_refusal",
    "load_dataset",
    "run_evaluation",
    "save_report",
    "score_case",
]
