"""Keyword search alongside the embedding, fused into one ranking.

An embedding spreads a long article's signal across everything the article
discusses, so one sentence stating a deadline ranks below the article's main
subject. Keyword search does not have that problem, and cannot follow a
paraphrase. Both run, and the two rankings are merged.
"""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from rag_agent.indexing.hybrid import RRF_CONSTANT, fuse, keyword_index, tokenise


def chunk(text: str, source: str = "doc.pdf") -> Document:
    return Document(page_content=text, metadata={"source": source})


class TestTokenise:
    def test_it_lowercases(self) -> None:
        assert tokenise("PRAZO Máximo") == ["prazo", "maximo"]

    def test_it_folds_accents(self) -> None:
        """Portuguese writes the same word both ways often enough to matter."""
        assert tokenise("suspensão") == tokenise("suspensao")

    def test_it_drops_punctuation(self) -> None:
        assert tokenise("Art. 70, §2º:") == ["art", "70", "2"]

    def test_it_keeps_numbers(self) -> None:
        """The deadlines and percentages are the point of this corpus."""
        assert "30" in tokenise("prazo de 30 dias")

    def test_empty_text_yields_nothing(self) -> None:
        assert tokenise("") == []


class TestFusion:
    def test_a_document_in_both_rankings_outranks_one_in_either(self) -> None:
        """The whole idea: agreement between retrievers is the signal."""
        both = chunk("both")
        only_first = chunk("only first")
        only_second = chunk("only second")

        fused = fuse([[only_first, both], [only_second, both]], limit=3)

        assert fused[0].page_content == "both"

    def test_a_higher_rank_scores_better(self) -> None:
        first = chunk("first")
        second = chunk("second")

        assert fuse([[first, second]], limit=2)[0].page_content == "first"

    def test_it_deduplicates_the_same_chunk(self) -> None:
        repeated = chunk("mesmo texto")

        assert len(fuse([[repeated], [repeated]], limit=5)) == 1

    def test_two_chunks_with_the_same_text_from_different_files_are_distinct(self) -> None:
        """Identity is the source plus the text, as it is for the stored ids."""
        assert len(fuse([[chunk("igual", "a.pdf"), chunk("igual", "b.pdf")]], limit=5)) == 2

    def test_it_cuts_to_the_limit(self) -> None:
        many = [chunk(str(n)) for n in range(20)]

        assert len(fuse([many], limit=4)) == 4

    def test_fusing_nothing_yields_nothing(self) -> None:
        assert fuse([], limit=5) == []

    def test_a_deep_hit_in_one_list_can_beat_a_shallow_miss_in_the_other(self) -> None:
        """Why the pool is wider than the number of passages wanted."""
        deep = chunk("deep")
        shallow_only = chunk("shallow")

        first = [chunk(f"v{n}") for n in range(3)] + [shallow_only]
        second = [chunk(f"k{n}") for n in range(2)] + [deep]

        fused = fuse([first, second], limit=8)

        assert fused.index(deep) < fused.index(shallow_only)

    def test_the_constant_is_the_published_one(self) -> None:
        assert RRF_CONSTANT == 60


class TestKeywordIndex:
    def test_it_ranks_by_word_overlap(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from rag_agent.indexing import hybrid

        class FakeStore:
            def get(self, include: list[str]) -> dict:
                return {
                    "documents": [
                        "A SRE pode suspender ou cancelar a oferta a qualquer tempo.",
                        "O prazo de suspensão da oferta não pode ser superior a 30 dias.",
                        "O lote suplementar não pode ultrapassar 15% da quantidade.",
                    ],
                    "metadatas": [{"source": "r.pdf"}] * 3,
                }

        monkeypatch.setattr("rag_agent.indexing.vector_store.get_vector_store", lambda: FakeStore())
        hybrid.forget_keyword_index()

        index = keyword_index()

        assert index is not None
        assert "30 dias" in index.rank("prazo de suspensão da oferta", 1)[0].page_content

    def test_an_empty_store_has_no_index(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A caller can then fall back to the vector search rather than fail."""
        from rag_agent.indexing import hybrid

        class EmptyStore:
            def get(self, include: list[str]) -> dict:
                return {"documents": [], "metadatas": []}

        monkeypatch.setattr(
            "rag_agent.indexing.vector_store.get_vector_store", lambda: EmptyStore()
        )
        hybrid.forget_keyword_index()

        assert keyword_index() is None

    def test_it_is_built_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from rag_agent.indexing import hybrid

        builds = 0

        class CountingStore:
            def get(self, include: list[str]) -> dict:
                nonlocal builds
                builds += 1
                return {"documents": ["texto"], "metadatas": [{"source": "r.pdf"}]}

        monkeypatch.setattr(
            "rag_agent.indexing.vector_store.get_vector_store", lambda: CountingStore()
        )
        hybrid.forget_keyword_index()

        keyword_index()
        keyword_index()

        assert builds == 1

    def test_forgetting_it_forces_a_rebuild(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The index is a copy, so it goes stale when the store changes."""
        from rag_agent.indexing import hybrid

        builds = 0

        class CountingStore:
            def get(self, include: list[str]) -> dict:
                nonlocal builds
                builds += 1
                return {"documents": ["texto"], "metadatas": [{"source": "r.pdf"}]}

        monkeypatch.setattr(
            "rag_agent.indexing.vector_store.get_vector_store", lambda: CountingStore()
        )
        hybrid.forget_keyword_index()

        keyword_index()
        hybrid.forget_keyword_index()
        keyword_index()

        assert builds == 2
