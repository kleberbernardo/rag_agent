"""Command line interface: presentation only, no domain logic.

rag ingest              build the index from data/
rag ask "question"      ask the agent once
rag chat                talk to the agent with memory
rag status              inspect the current configuration and index
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from rag_agent.agent import ChatSession, ask, format_trace
from rag_agent.config import PROJECT_ROOT, get_settings
from rag_agent.evaluation import (
    DEFAULT_DATASET,
    CaseScore,
    EvalReport,
    build_report,
    load_dataset,
    run_evaluation,
    save_report,
)
from rag_agent.indexing import (
    VectorStoreUnavailableError,
    count_documents,
    describe_location,
    index_documents,
    load_documents,
    split_documents,
)
from rag_agent.logging_setup import setup_logging
from rag_agent.observability import flush as flush_traces
from rag_agent.types import AnswerResult, RunMetrics

app = typer.Typer(
    add_completion=False,
    help="Agente RAG sobre a sua própria base de documentos.",
)
console = Console()

_EMPTY_INDEX_HINT = "[yellow]O índice está vazio. Rode primeiro:[/] rag ingest"
_EXIT_WORDS = frozenset({"sair", "exit", "quit"})

VerboseOption = typer.Option(False, "--verbose", "-v", help="Mostra logs detalhados.")
TraceOption = typer.Option(False, "--trace", "-t", help="Mostra o raciocínio do agente.")
DatasetOption = typer.Option(DEFAULT_DATASET, "--dataset", "-d", help="Arquivo do dataset.")
LimitOption = typer.Option(0, "--limit", "-n", help="Roda apenas os N primeiros casos.")
SaveOption = typer.Option(True, "--save/--no-save", help="Grava o relatório em evals/results.")


@app.command()
def ingest(verbose: bool = VerboseOption) -> None:
    """Lê os documentos de data/, quebra em pedaços e indexa no banco vetorial."""
    setup_logging(verbose=verbose)
    settings = get_settings()

    with console.status("[cyan]Carregando documentos..."):
        documents = load_documents(settings.data_dir)

    if not documents:
        console.print(f"[yellow]Nenhum documento encontrado em {settings.data_dir}")
        raise typer.Exit(code=1)

    console.print(f"[green]OK[/] {len(documents)} documento(s) carregado(s)")

    chunks = split_documents(
        documents,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    console.print(f"[green]OK[/] {len(chunks)} pedaço(s) gerado(s)")

    with console.status("[cyan]Gerando embeddings e indexando..."):
        total = index_documents(chunks)

    console.print(f"[green]OK[/] {total} pedaço(s) indexado(s) em {describe_location()}")


@app.command(name="ask")
def ask_command(
    question: str = typer.Argument(..., help="A pergunta em linguagem natural."),
    trace: bool = TraceOption,
    verbose: bool = VerboseOption,
) -> None:
    """Pergunta ao agente, que decide sozinho quais ferramentas usar."""
    setup_logging(verbose=verbose)
    _require_index()

    with console.status("[cyan]Pensando..."):
        result = ask(question)

    _render(result, show_trace=trace)
    flush_traces()


@app.command()
def chat(trace: bool = TraceOption, verbose: bool = VerboseOption) -> None:
    """Conversa contínua com o agente, com memória entre as perguntas."""
    setup_logging(verbose=verbose)
    _require_index()

    session = ChatSession()
    console.print(
        Panel(
            "Converse com o agente. Ele lembra do que já foi dito.\n"
            "Digite [bold]sair[/] para encerrar.",
            title="modo conversa",
            border_style="cyan",
        )
    )

    while True:
        question = _read_question()
        if question is None:
            console.print("\n[dim]até mais.")
            break
        if not question:
            continue
        if question.lower() in _EXIT_WORDS:
            console.print("[dim]até mais.")
            flush_traces()
            break

        with console.status("[cyan]pensando..."):
            result = session.send(question)

        console.print(f"[bold green]agente[/] > {escape(result.answer)}")
        if trace:
            console.print(f"[dim]ferramentas: {', '.join(result.tool_names) or 'nenhuma'}")
            if result.metrics:
                console.print(f"[dim]{_format_metrics(result.metrics)}")


@app.command()
def status() -> None:
    """Mostra a configuração ativa e quantos pedaços estão indexados."""
    settings = get_settings()
    total = _count_or_exit()

    console.print(f"[bold]modelo      [/] {settings.chat_model}")
    console.print(f"[bold]embeddings  [/] {settings.embedding_model}")
    console.print(f"[bold]chunk       [/] {settings.chunk_size} / overlap {settings.chunk_overlap}")
    console.print(f"[bold]domínio     [/] {settings.knowledge_domain}")
    console.print(f"[bold]documentos  [/] {settings.data_dir}")
    console.print(
        f"[bold]índice      [/] {settings.vector_store_mode.value} · {describe_location()}"
    )
    console.print(f"[bold]indexado    [/] [{'green' if total else 'yellow'}]{total} pedaço(s)")


@app.command(name="eval")
def eval_command(
    dataset: Path = DatasetOption,
    limit: int = LimitOption,
    save: bool = SaveOption,
    verbose: bool = VerboseOption,
) -> None:
    """Mede o agente contra perguntas cuja resposta é conhecida."""
    setup_logging(verbose=verbose)
    _require_index()

    cases = load_dataset(dataset)
    if limit > 0:
        cases = cases[:limit]

    scores: list[CaseScore] = []
    with console.status(f"[cyan]Avaliando {len(cases)} caso(s)...") as spinner:
        for score in run_evaluation(cases):
            scores.append(score)
            spinner.update(f"[cyan]Avaliando... {len(scores)}/{len(cases)} · {score.case_id}")
            console.print(
                f"  {'[green]PASS[/]' if score.passed else '[red]FAIL[/]'} {score.case_id}"
            )

    report = build_report(scores)
    _render_report(report)

    if save:
        path = save_report(report, PROJECT_ROOT / "evals" / "results")
        console.print(f"[dim]relatório salvo em {path}")

    # Non-zero exit makes the suite usable as a gate in CI or a pre-release check.
    if report.failures:
        raise typer.Exit(code=1)


def _render_report(report: EvalReport) -> None:
    """Print the summary, then the failures, because failures are the point."""
    table = Table(title="avaliação", border_style="cyan")
    table.add_column("métrica")
    table.add_column("resultado", justify="right")
    table.add_column("o que mede", style="dim")

    table.add_row("retrieval", report.retrieval_accuracy.percent, "trouxe o documento certo")
    table.add_row("citação", report.citation_accuracy.percent, "citou a fonte certa")
    table.add_row("fato", report.factual_accuracy.percent, "o número ou termo esperado apareceu")
    table.add_row("recusa", report.refusal_accuracy.percent, "admitiu não saber, fora do corpus")
    table.add_row("geral", report.overall.percent, "passou em tudo que se aplicava")
    console.print(table)

    console.print(
        f"[dim]{report.model} · k={report.retrieval_k} · "
        f"mediana {report.median_latency:.2f}s · "
        f"{report.total_tokens} tokens · ~US$ {report.total_cost_usd:.4f}"
    )

    if not report.failures:
        return

    console.print(f"\n[red]{len(report.failures)} falha(s):")
    for score in report.failures:
        console.print(f"\n[bold]{score.case_id}[/] — {escape(score.question)}")
        if score.error:
            console.print(f"  [red]erro:[/] {escape(score.error[:160])}")
            continue
        console.print(f"  [dim]recuperou:[/] {', '.join(score.retrieved_sources) or 'nada'}")
        console.print(f"  [dim]respondeu:[/] {escape(score.answer[:180])}")
        for label, value in (
            ("retrieval", score.retrieval_hit),
            ("citação", score.citation_correct),
            ("fato", score.facts_present),
            ("recusa", score.refusal_correct),
        ):
            if value is False:
                console.print(f"  [red]falhou em {label}")


def _require_index() -> None:
    """Stop early when there is nothing to search: the answer would be useless."""
    if _count_or_exit() == 0:
        console.print(_EMPTY_INDEX_HINT)
        raise typer.Exit(code=1)


def _count_or_exit() -> int:
    """Count indexed chunks, turning an unreachable server into a clean exit."""
    try:
        return count_documents()
    except VectorStoreUnavailableError as error:
        console.print(f"[red]{error}")
        raise typer.Exit(code=1) from error


def _read_question() -> str | None:
    """Read one line from the user. None means the user asked to leave."""
    try:
        return console.input("\n[bold cyan]você[/] > ").strip()
    except (KeyboardInterrupt, EOFError):
        return None


def _render(result: AnswerResult, *, show_trace: bool) -> None:
    if show_trace:
        console.print(
            Panel(
                escape(format_trace(result.messages)),
                title="raciocínio",
                border_style="dim",
            )
        )

    console.print(Panel(escape(result.answer), title="resposta", border_style="green"))

    if result.used_tools:
        console.print(f"[dim]ferramentas usadas: {', '.join(result.tool_names)}")

    if result.metrics:
        console.print(f"[dim]{_format_metrics(result.metrics)}")


def _format_metrics(metrics: RunMetrics) -> str:
    """One line of usage: what the run took and what it cost."""
    parts = [
        f"{metrics.latency_seconds:.2f}s",
        f"{metrics.total_tokens} tokens ({metrics.input_tokens} in / {metrics.output_tokens} out)",
        f"{metrics.tool_calls} tool call(s)",
    ]
    # An unlisted model yields no estimate; showing nothing beats showing a
    # number that looks authoritative and is wrong.
    if metrics.estimated_cost_usd is not None:
        parts.append(f"~US$ {metrics.estimated_cost_usd:.5f}")
    return " · ".join(parts)


if __name__ == "__main__":
    app()
