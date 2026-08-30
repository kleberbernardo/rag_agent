"""The evaluation harness itself: it has to be trustworthy before its scores are."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from rag_agent.evaluation import (
    EvalCase,
    build_report,
    error_score,
    extract_retrieved_sources,
    is_refusal,
    load_dataset,
    run_evaluation,
    save_report,
    score_case,
)
from rag_agent.evaluation.runner import Rate
from rag_agent.types import AnswerResult, RunMetrics

SOURCE = "cvm-resolucao-160-ofertas-publicas.pdf"


def answer(text: str, sources: list[str] | None = None) -> AnswerResult:
    """An AnswerResult shaped like a real run, including the tool output."""
    messages: list = []
    for source in sources or []:
        messages.append(
            ToolMessage(
                content=f"--- Trecho 1 [fonte: {source} | distância 0.512]\nconteúdo",
                tool_call_id="1",
                name="search_documentation",
            )
        )
    messages.append(AIMessage(content=text))

    return AnswerResult(
        answer=text,
        messages=messages,
        metrics=RunMetrics(
            latency_seconds=1.0,
            input_tokens=100,
            output_tokens=10,
            tool_calls=1,
            model="gpt-4o-mini",
            estimated_cost_usd=0.0001,
        ),
    )


def case(**overrides: object) -> EvalCase:
    defaults: dict = {
        "id": "c1",
        "question": "qual o limite?",
        "expected_source": SOURCE,
        "expected_facts": ["15"],
        "reference_answer": "15%",
        "tags": [],
    }
    defaults.update(overrides)
    return EvalCase(**defaults)  # type: ignore[arg-type]


class TestDataset:
    def test_ships_a_dataset_that_loads(self) -> None:
        assert len(load_dataset()) >= 20

    def test_the_shipped_dataset_has_out_of_corpus_cases(self) -> None:
        """Without them, nothing measures whether the agent invents answers."""
        cases = load_dataset()

        assert any(not c.answerable for c in cases)

    def test_every_answerable_case_expects_a_fact(self) -> None:
        assert all(c.expected_facts for c in load_dataset() if c.answerable)

    def test_missing_file_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_dataset(tmp_path / "nao-existe.json")

    def test_duplicate_ids_are_rejected(self, tmp_path: Path) -> None:
        """A repeated id would silently overwrite a result in the report."""
        path = tmp_path / "dup.json"
        entry = {"id": "same", "question": "q", "expected_source": SOURCE}
        path.write_text(json.dumps({"cases": [entry, entry]}), encoding="utf-8")

        with pytest.raises(ValueError, match="Ids repetidos"):
            load_dataset(path)


class TestSourceExtraction:
    def test_reads_the_source_label_the_tool_emits(self) -> None:
        result = answer("resposta", sources=[SOURCE])

        assert extract_retrieved_sources(result.messages) == [SOURCE]

    def test_deduplicates_repeated_sources(self) -> None:
        result = answer("resposta", sources=[SOURCE, SOURCE])

        assert extract_retrieved_sources(result.messages) == [SOURCE]

    def test_no_tool_output_means_no_sources(self) -> None:
        assert extract_retrieved_sources(answer("resposta").messages) == []


class TestRefusalDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "não encontrei isso na documentação.",
            "NAO ENCONTREI nada.",
            "Nenhum trecho relevante encontrado.",
        ],
    )
    def test_recognises_a_refusal_despite_case_and_accents(self, text: str) -> None:
        assert is_refusal(text) is True

    def test_a_real_answer_is_not_a_refusal(self) -> None:
        assert is_refusal("O limite é de 15% (fonte: x.pdf)") is False


class TestScoringAnswerable:
    def test_a_correct_answer_passes_everything(self) -> None:
        score = score_case(case(), answer(f"O limite é 15% (fonte: {SOURCE})", [SOURCE]))

        assert score.retrieval_hit is True
        assert score.citation_correct is True
        assert score.facts_present is True
        assert score.passed is True

    def test_right_document_wrong_number_fails_on_fact_alone(self) -> None:
        """The dangerous case: correct citation makes a wrong number look sound."""
        score = score_case(case(), answer(f"O limite é 5% (fonte: {SOURCE})", [SOURCE]))

        assert score.retrieval_hit is True
        assert score.citation_correct is True
        assert score.facts_present is False
        assert score.passed is False

    def test_missing_citation_fails(self) -> None:
        score = score_case(case(), answer("O limite é 15%", [SOURCE]))

        assert score.citation_correct is False
        assert score.passed is False

    def test_wrong_document_fails_retrieval(self) -> None:
        score = score_case(case(), answer("O limite é 15%", ["outro.pdf"]))

        assert score.retrieval_hit is False


class TestScoringOutOfCorpus:
    def test_admitting_ignorance_passes(self) -> None:
        score = score_case(
            case(expected_source=None, expected_facts=[]),
            answer("não encontrei isso na documentação."),
        )

        assert score.refusal_correct is True
        assert score.passed is True

    def test_inventing_an_answer_fails(self) -> None:
        score = score_case(
            case(expected_source=None, expected_facts=[]),
            answer("A alíquota é de 20%."),
        )

        assert score.refusal_correct is False
        assert score.passed is False

    def test_retrieval_metrics_do_not_apply(self) -> None:
        score = score_case(case(expected_source=None, expected_facts=[]), answer("não encontrei"))

        assert score.retrieval_hit is None
        assert score.citation_correct is None


class TestErrorIsolation:
    """One pathological question must not end the suite."""

    def test_a_raising_case_is_recorded_as_a_failure(self) -> None:
        def explode(_: str) -> AnswerResult:
            msg = "recursion limit"
            raise RuntimeError(msg)

        scores = list(run_evaluation([case()], ask_function=explode))

        assert len(scores) == 1
        assert scores[0].passed is False
        assert "RuntimeError" in (scores[0].error or "")

    def test_the_suite_continues_past_a_failure(self) -> None:
        calls: list[str] = []

        def sometimes_explode(question: str) -> AnswerResult:
            calls.append(question)
            if len(calls) == 1:
                msg = "boom"
                raise RuntimeError(msg)
            return answer(f"O limite é 15% (fonte: {SOURCE})", [SOURCE])

        cases = [case(id="a", question="q1"), case(id="b", question="q2")]
        scores = list(run_evaluation(cases, ask_function=sometimes_explode))

        assert len(scores) == 2
        assert scores[0].passed is False
        assert scores[1].passed is True

    def test_error_score_carries_the_exception_type(self) -> None:
        score = error_score(case(), ValueError("detalhe"))

        assert score.error is not None
        assert "ValueError" in score.error
        assert "detalhe" in score.error


class TestRate:
    def test_reports_a_percentage(self) -> None:
        assert Rate(passed=9, total=10).percent == "90%"

    def test_nothing_applicable_is_not_zero_percent(self) -> None:
        """0 of 0 means "did not apply", which is not the same as failing."""
        assert Rate(passed=0, total=0).percent == "n/a"
        assert Rate(passed=0, total=0).ratio is None


class TestReport:
    def test_aggregates_each_metric(self) -> None:
        good = score_case(case(), answer(f"15% (fonte: {SOURCE})", [SOURCE]))
        bad = score_case(case(id="c2"), answer(f"5% (fonte: {SOURCE})", [SOURCE]))

        report = build_report([good, bad])

        assert report.overall.percent == "50%"
        assert report.retrieval_accuracy.percent == "100%"
        assert report.factual_accuracy.percent == "50%"

    def test_records_the_settings_that_produced_it(self) -> None:
        """A score without its configuration cannot be compared to the next run."""
        report = build_report([])

        assert report.model
        assert report.retrieval_k > 0
        assert report.started_at

    def test_sums_cost_and_tokens(self) -> None:
        score = score_case(case(), answer(f"15% (fonte: {SOURCE})", [SOURCE]))

        report = build_report([score, score])

        assert report.total_tokens == 220
        assert report.total_cost_usd == pytest.approx(0.0002)

    def test_lists_only_the_failures(self) -> None:
        good = score_case(case(), answer(f"15% (fonte: {SOURCE})", [SOURCE]))
        bad = score_case(case(id="c2"), answer("5%", []))

        assert [s.case_id for s in build_report([good, bad]).failures] == ["c2"]

    def test_saves_a_readable_report(self, tmp_path: Path) -> None:
        score = score_case(case(), answer(f"15% (fonte: {SOURCE})", [SOURCE]))

        path = save_report(build_report([score]), tmp_path)
        written = json.loads(path.read_text(encoding="utf-8"))

        assert written["summary"]["cases"] == 1
        assert written["cases"][0]["id"] == "c1"
