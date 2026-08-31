"""Keyword search alongside the vector search, fused into one ranking.

An embedding compares meaning, which is what lets "quanto custa o plano mais
barato" find a passage that says neither word. It also spreads a long article's
signal across everything that article talks about, so one sentence stating a
deadline sits below whatever the article is mostly about.

BM25 compares words. It cannot follow a paraphrase, and it does not need to
when the question names the terms the text uses.

Neither wins on its own, so both run and the two rankings are fused. Measured
on this corpus, the passage stating the suspension deadline sits at rank 31 by
embedding and at rank 5 by keyword.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# Reciprocal rank fusion. The constant damps the top of each list so one
# retriever cannot dominate the other with a single confident hit; 60 is the
# value from the paper the method comes from, and the one every implementation
# starts with.
RRF_CONSTANT = 60

# Each retriever is asked for this many times the number of passages wanted,
# and the fused list is cut back to it. Fusing two short lists rewards the
# documents both retrievers already agreed on, which are the ones a single
# retriever would have found anyway; the passages worth adding sit deeper in
# one list. Measured on this corpus, the suspension deadline reaches the top
# eight at a multiplier of five and not at three.
FUSION_POOL = 5

_WORD = re.compile(r"[a-z0-9]+")

# The ordinal marks are compatibility characters that decompose into letters,
# turning "§2º" into "2o" and hiding it from a search for "§ 2". This corpus is
# written in articles and paragraphs, so it is full of them.
_ORDINALS = str.maketrans("", "", "ºª°")


@dataclass(frozen=True, slots=True)
class KeywordIndex:
    """A BM25 index over every chunk currently stored."""

    engine: object
    documents: list[Document]

    def rank(self, query: str, limit: int) -> list[Document]:
        """The documents most similar to the query by word overlap."""
        scores = self.engine.get_scores(tokenise(query))  # type: ignore[attr-defined]
        best = sorted(range(len(scores)), key=lambda index: -scores[index])[:limit]

        return [self.documents[index] for index in best]


def tokenise(text: str) -> list[str]:
    """Words, lowercased and stripped of accents.

    Portuguese writes the same word with and without an accent often enough
    that folding them together is worth more than the precision it costs.
    """
    stripped = text.lower().translate(_ORDINALS)
    decomposed = unicodedata.normalize("NFKD", stripped)
    folded = "".join(char for char in decomposed if not unicodedata.combining(char))

    return _WORD.findall(folded)


@lru_cache(maxsize=1)
def keyword_index() -> KeywordIndex | None:
    """Build the BM25 index from what is stored, once.

    Returns None when the store is empty or the dependency is missing, so a
    caller can fall back to the vector search rather than fail.
    """
    from rag_agent.indexing.vector_store import get_vector_store

    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        logger.warning("rank_bm25 is not installed; keyword search is unavailable.")
        return None

    stored = get_vector_store().get(include=["documents", "metadatas"])
    texts = stored.get("documents") or []
    if not texts:
        return None

    metadatas = stored.get("metadatas") or [{}] * len(texts)
    documents = [
        Document(page_content=text, metadata=dict(metadata or {}))
        for text, metadata in zip(texts, metadatas, strict=False)
    ]

    logger.info("Built the keyword index over %d chunk(s)", len(documents))
    return KeywordIndex(engine=BM25Okapi([tokenise(text) for text in texts]), documents=documents)


def forget_keyword_index() -> None:
    """Drop the cached index, after the stored chunks change."""
    keyword_index.cache_clear()


def fuse(rankings: list[list[Document]], limit: int) -> list[Document]:
    """Merge several rankings into one by reciprocal rank fusion.

    Each document scores the sum of 1/(constant + rank) across the lists it
    appears in, so a document ranked well by both retrievers outranks one
    ranked brilliantly by a single retriever. Fusing on rank rather than on
    score is what makes it work at all: a cosine distance and a BM25 score are
    not on the same scale and cannot be added.
    """
    scores: dict[str, float] = {}
    seen: dict[str, Document] = {}

    for ranking in rankings:
        for rank, document in enumerate(ranking, start=1):
            key = _identity(document)
            seen.setdefault(key, document)
            scores[key] = scores.get(key, 0.0) + 1 / (RRF_CONSTANT + rank)

    best = sorted(scores, key=lambda key: -scores[key])[:limit]
    return [seen[key] for key in best]


def _identity(document: Document) -> str:
    """What makes two results the same chunk, across two retrievers."""
    return f"{document.metadata.get('source', '')}::{document.page_content}"
