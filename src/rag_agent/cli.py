"""Command line interface: presentation only, no domain logic.

rag ingest              build the index from data/
rag ask "question"      ask the agent once
rag chat                talk to the agent with memory
rag status              inspect the current configuration and index
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from rag_agent.agent import ChatSession, ask, format_trace
from rag_agent.config import PROJECT_ROOT, get_settings
from rag_agent.evaluation import (
    DATASET_NAME,
    DEFAULT_DATASET,
    CaseScore,
    Comparison,
    EvalReport,
    LangfuseUnavailableError,
    build_report,
    capture_configuration,
    compare,
    load_dataset,
    load_report,
    run_evaluation,
    run_experiment,
    save_report,
    summarise,
    sync_dataset,
)
from rag_agent.indexing import (
    DatabaseUnavailableError,
    count_documents,
    delete_source,
    describe_location,
    index_documents,
    list_sources,
    load_documents,
    reranking_enabled,
    reset_index,
    split_documents,
)
from rag_agent.observability import flush as flush_traces
from rag_agent.observability import publish_prompt, setup_logging
from rag_agent.prompts import (
    build_search_tool_description,
    build_system_prompt,
    describe_source,
)
from rag_agent.prompts.templates import PUBLISHED_PROMPTS
from rag_agent.types import AnswerResult, RunMetrics

app = typer.Typer(
    add_completion=False,
    help="Agente RAG sobre a sua própria base de documentos.",
)
console = Console()

_EMPTY_INDEX_HINT = "[yellow]O índice está vazio. Rode primeiro:[/] rag ingest"
_EXIT_WORDS = frozenset({"sair", "exit", "quit"})

# One description per metric, so the local table and the platform table say
# the same thing about the same number.
# Names follow the RAG evaluation literature, so a reader who knows RAGAS or
# LangSmith recognises what each one measures. The second column says what the
# name means in this project, since the same word is used loosely elsewhere.
#
# The first four compare the answer against the dataset's expected output.
# The last two compare it against what the agent retrieved, which is why they
# also work on production traffic, where no expected answer exists.
_METRIC_LABELS = {
    "retrieval": "the right document came back",
    "citation": "the answer names the right source",
    "correctness": "the expected number or term is present",
    "refusal": "admitted not knowing, outside the corpus",
    "groundedness": "every number came from what it read",
    "faithfulness": "the sentence matches the passage (model-graded)",
}

VerboseOption = typer.Option(False, "--verbose", "-v", help="Mostra logs detalhados.")
TraceOption = typer.Option(False, "--trace", "-t", help="Mostra o raciocínio do agente.")
DatasetOption = typer.Option(DEFAULT_DATASET, "--dataset", "-d", help="Arquivo do dataset.")
LimitOption = typer.Option(0, "--limit", "-n", help="Roda apenas os N primeiros casos.")
SaveOption = typer.Option(True, "--save/--no-save", help="Grava o relatório em evals/results.")
CompareOption = typer.Option(None, "--compare", "-c", help="Compara com um relatório anterior.")
MaxCostOption = typer.Option(
    0.0,
    "--max-cost",
    min=0.0,
    help="Custo máximo em US$ para a execução inteira. 0 desliga a checagem.",
)
JudgeOption = typer.Option(
    True,
    "--judge/--no-judge",
    help="A métrica faithfulness, julgada por um modelo. Ligada por padrão; custa tokens.",
)
MinScoreOption = typer.Option(
    1.0,
    "--min-score",
    min=0.0,
    max=1.0,
    help="Nota geral mínima para o comando sair com sucesso. 1.0 exige tudo.",
)
HostOption = typer.Option("127.0.0.1", "--host", help="Endereço de escuta.")
PortOption = typer.Option(8080, "--port", "-p", help="Porta.")
ReloadOption = typer.Option(False, "--reload", help="Reinicia ao salvar arquivo (desenvolvimento).")
RemoveOption = typer.Option(
    None,
    "--remove",
    help="Remove do índice todos os pedaços deste documento. Use o nome exato do arquivo.",
)
YesOption = typer.Option(False, "--yes", "-y", help="Não pede confirmação.")
ResetOption = typer.Option(
    False, "--reset", help="Apaga o índice antes de indexar. Use ao trocar de estratégia."
)


prompt_app = typer.Typer(
    add_completion=False,
    help="Gerencia os prompts publicados no Langfuse.",
)
app.add_typer(prompt_app, name="prompt")

CommitMessageOption = typer.Option(
    "publicado pela CLI", "--message", "-m", help="Mensagem da versão."
)


@prompt_app.command("show")
def prompt_show(verbose: bool = VerboseOption) -> None:
    """Mostra o prompt em vigor e de onde ele veio."""
    setup_logging(verbose=verbose)
    settings = get_settings()
    source, version = describe_source()

    origem = f"Langfuse v{version}" if version is not None else "código local"
    console.print(f"[bold]origem      [/] {origem}")
    console.print(f"[bold]label       [/] {settings.prompt_label}")
    console.print(f"[bold]domínio     [/] {settings.knowledge_domain}")

    console.print(Panel(escape(build_system_prompt()), title="system", border_style="cyan"))
    console.print(
        Panel(
            escape(build_search_tool_description()),
            title="search_documentation",
            border_style="dim",
        )
    )

    if source == "local":
        console.print(
            "[dim]Publique com [/]rag prompt push[dim] para poder versionar e "
            "trocar sem novo deploy."
        )


@prompt_app.command("push")
def prompt_push(
    message: str = CommitMessageOption,
    verbose: bool = VerboseOption,
) -> None:
    """Publica os prompts locais no Langfuse, sob o label configurado."""
    setup_logging(verbose=verbose)
    settings = get_settings()

    if not settings.tracing_enabled:
        console.print("[yellow]Langfuse não configurado. Nada a publicar.")
        raise typer.Exit(code=1)

    for name, template in PUBLISHED_PROMPTS.items():
        version = publish_prompt(
            name, template, label=settings.prompt_label, commit_message=message
        )
        if version is None:
            console.print(f"[red]falhou[/] {name}")
            raise typer.Exit(code=1)
        console.print(f"[green]OK[/] {name} v{version} ({settings.prompt_label})")

    console.print(
        f"[dim]Edite no Langfuse e mova o label {settings.prompt_label} para trocar de versão."
    )


dataset_app = typer.Typer(
    add_completion=False,
    help="Publica o dataset de avaliação no Langfuse.",
)
app.add_typer(dataset_app, name="dataset")

RunNameOption = typer.Option(
    None, "--name", help="Nome da execução no Langfuse. O padrão é modelo, k e data."
)


@dataset_app.command("push")
def dataset_push(
    dataset: Path = DatasetOption,
    verbose: bool = VerboseOption,
) -> None:
    """Envia o dataset local para o Langfuse, criando ou atualizando os itens."""
    setup_logging(verbose=verbose)
    cases = load_dataset(dataset)

    with console.status(f"[cyan]Enviando {len(cases)} caso(s)..."):
        total = _with_langfuse(lambda: sync_dataset(cases))

    console.print(f"[green]OK[/] {total} item(ns) em [bold]{DATASET_NAME}[/]")
    console.print("[dim]O arquivo continua no git: dataset versionado com o código é o padrão.")


def _today() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y%m%d-%H%M")


def _with_langfuse[T](action: Callable[[], T]) -> T:
    """Run something that needs the platform, or exit saying it is missing."""
    try:
        return action()
    except LangfuseUnavailableError as error:
        console.print(f"[yellow]{error}")
        raise typer.Exit(code=1) from error


@app.command()
def ingest(reset: bool = ResetOption, verbose: bool = VerboseOption) -> None:
    """Lê os documentos de data/, quebra em pedaços e indexa no banco vetorial."""
    setup_logging(verbose=verbose)
    settings = get_settings()

    if reset:
        with console.status("[cyan]Limpando o índice..."):
            reset_index()
        console.print("[green]OK[/] índice limpo")

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
        strategy=settings.chunk_strategy,
        article_max_chars=settings.article_max_chars,
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
    console.print(
        f"[bold]chunk       [/] {settings.chunk_strategy.value} · "
        f"{settings.chunk_size} / overlap {settings.chunk_overlap}"
    )
    console.print(f"[bold]domínio     [/] {settings.knowledge_domain}")
    console.print(f"[bold]documentos  [/] {settings.data_dir}")
    console.print(f"[bold]índice      [/] postgres · {describe_location()}")
    console.print(f"[bold]busca       [/] {settings.search_strategy.value}")
    console.print(
        f"[bold]rerank      [/] {settings.rerank_strategy.value}"
        + (
            f" · {settings.rerank_model} · {settings.rerank_candidates} candidatos"
            if reranking_enabled()
            else ""
        )
    )
    console.print(f"[bold]indexado    [/] [{'green' if total else 'yellow'}]{total} pedaço(s)")


@app.command()
def sources(source: str = RemoveOption, yes: bool = YesOption) -> None:
    """Lista os documentos indexados, ou remove um deles do índice."""
    if source is None:
        _print_sources()
        return

    _remove_source(source, confirmed=yes)


def _print_sources() -> None:
    """Show what is indexed, grouped by the document it came from."""
    indexed = list_sources()

    if not indexed:
        console.print("[yellow]O índice está vazio. Rode: rag ingest[/]")
        return

    table = Table(title="documentos indexados", border_style="cyan")
    table.add_column("documento", style="bold")
    table.add_column("pedaços", justify="right")

    for entry in indexed:
        table.add_row(entry.name or "[sem origem]", str(entry.chunks))

    console.print(table)
    console.print(
        f"\n{len(indexed)} documento(s), {sum(entry.chunks for entry in indexed)} pedaço(s)"
    )


def _remove_source(source: str, *, confirmed: bool) -> None:
    """Remove one document, after saying exactly what will disappear.

    Re-ingesting overwrites a chunk whose text is unchanged, so it cannot undo
    a removal by itself: a document taken out of the index comes back only if
    its file is still in data/ and ingestion runs again.
    """
    known = {entry.name: entry.chunks for entry in list_sources()}

    if source not in known:
        console.print(f"[red]'{source}' não está indexado.[/]")
        if known:
            console.print("\nIndexados no momento:")
            for name in known:
                console.print(f"  {name}")
        raise typer.Exit(code=1)

    if not confirmed:
        confirmed = typer.confirm(f"Remover {known[source]} pedaço(s) de '{source}'?")

    if not confirmed:
        console.print("Cancelado.")
        return

    removed = delete_source(source)
    console.print(f"[green]Removido:[/] {removed} pedaço(s) de '{source}'")


@app.command(name="eval")
def eval_command(
    dataset: Path = DatasetOption,
    limit: int = LimitOption,
    save: bool = SaveOption,
    compare_with: Path | None = CompareOption,
    min_score: float = MinScoreOption,
    max_cost: float = MaxCostOption,
    judge: bool = JudgeOption,
    name: str | None = RunNameOption,
    verbose: bool = VerboseOption,
) -> None:
    """Mede o agente contra perguntas cuja resposta é conhecida.

    Com o Langfuse configurado, as perguntas vêm do dataset publicado lá e as
    notas voltam para ele. Sem, o arquivo local é lido e um relatório é
    gravado. O agente e as métricas rodam nesta máquina nos dois casos: nenhuma
    plataforma executa a sua aplicação.
    """
    setup_logging(verbose=verbose)
    _require_index()

    cases = load_dataset(dataset)
    if limit > 0:
        cases = cases[:limit]

    # No flag chooses the destination. Configured Langfuse means the questions
    # come from the dataset there and the scores go back to it; without it the
    # file is read and a report is written. One command, one behaviour, and the
    # decision belongs to the environment rather than to whoever types it.
    if get_settings().tracing_enabled:
        _evaluate_on_langfuse(name=name, with_judge=judge, min_score=min_score)
        return

    scores: list[CaseScore] = []
    with console.status(f"[cyan]Avaliando {len(cases)} caso(s)...") as spinner:
        for score in run_evaluation(cases, with_judge=judge):
            scores.append(score)
            spinner.update(f"[cyan]Avaliando... {len(scores)}/{len(cases)} · {score.case_id}")
            console.print(
                f"  {'[green]PASS[/]' if score.passed else '[red]FAIL[/]'} {score.case_id}"
            )

    report = build_report(scores)
    _render_report(report)

    if compare_with is not None:
        _render_comparison(compare(load_report(compare_with), report), compare_with)

    if save:
        path = save_report(report, PROJECT_ROOT / "evals" / "results")
        console.print(f"[dim]relatório salvo em {path}")

    # A verbose prompt or a larger k shows up here as a number rather than as a
    # surprise on the invoice.
    if max_cost and report.total_cost_usd > max_cost:
        console.print(
            f"\n[red]acima do teto de custo:[/] "
            f"US$ {report.total_cost_usd:.4f} > US$ {max_cost:.4f}"
        )
        raise typer.Exit(code=1)

    # A threshold rather than "every case must pass": one known failure should
    # not block a release, while a real regression should.
    overall = report.overall.ratio or 0.0
    if overall < min_score:
        # One decimal, because 26 of 29 rounds to 90% and reading
        # "90% < 90%" as the reason for a failure helps nobody.
        console.print(f"\n[red]abaixo do limiar:[/] {overall:.1%} < {min_score:.1%}")
        raise typer.Exit(code=1)


def _evaluate_on_langfuse(*, name: str | None, with_judge: bool, min_score: float) -> None:
    """Run the same suite on the platform, and report it the same way here.

    Langfuse keeps the detail and the comparison; the terminal still gets the
    table, because having to open a browser to learn whether the suite passed
    is a worse trade than the history is worth.
    """
    settings = get_settings()
    run_name = name or f"{settings.chat_model}-k{settings.retrieval_k}-{_today()}"
    configuration = capture_configuration().to_dict()
    configuration.pop("prompt")

    with console.status(f"[cyan]Avaliando no Langfuse: {run_name}..."):
        result = _with_langfuse(
            lambda: run_experiment(
                name=run_name,
                description=f"chunking {settings.chunk_strategy.value}, k={settings.retrieval_k}",
                metadata=configuration,
                with_judge=with_judge,
            )
        )

    counts = summarise(result)
    _render_counts(counts, run_name)

    url = getattr(result, "dataset_run_url", None)
    if url:
        console.print(f"[dim]{url}")

    overall = _overall_of(counts)
    if overall < min_score:
        console.print(f"\n[red]abaixo do limiar:[/] {overall:.1%} < {min_score:.1%}")
        raise typer.Exit(code=1)


def _render_counts(counts: dict[str, tuple[int, int]], run_name: str) -> None:
    """The same table the local run prints, built from the platform's result."""
    table = Table(title=f"avaliação · {run_name}", border_style="cyan")
    table.add_column("metric")
    table.add_column("score", justify="right")
    table.add_column("what it measures", style="dim")

    for metric, description in _METRIC_LABELS.items():
        if metric not in counts:
            continue
        passed, total = counts[metric]
        table.add_row(metric, f"{passed / total:.0%}" if total else "n/a", description)

    passed, total = _totals(counts)
    table.add_row("overall", f"{passed / total:.0%}" if total else "n/a", "positive scores overall")
    console.print(table)


def _overall_of(counts: dict[str, tuple[int, int]]) -> float:
    passed, total = _totals(counts)
    return passed / total if total else 0.0


def _totals(counts: dict[str, tuple[int, int]]) -> tuple[int, int]:
    return (
        sum(passed for passed, _ in counts.values()),
        sum(total for _, total in counts.values()),
    )


def _render_report(report: EvalReport) -> None:
    """Print the summary, then the failures, because failures are the point."""
    table = Table(title="avaliação", border_style="cyan")
    table.add_column("metric")
    table.add_column("score", justify="right")
    table.add_column("what it measures", style="dim")

    table.add_row("retrieval", report.retrieval_accuracy.percent, "trouxe o documento certo")
    table.add_row("citação", report.citation_accuracy.percent, "citou a fonte certa")
    table.add_row("fato", report.factual_accuracy.percent, "o número ou termo esperado apareceu")
    table.add_row("recusa", report.refusal_accuracy.percent, "admitiu não saber, fora do corpus")
    table.add_row("fundamentação", report.groundedness.percent, "todo número saiu do que ele leu")
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
            ("citation", score.citation_correct),
            ("correctness", score.facts_present),
            ("refusal", score.refusal_correct),
            ("groundedness", score.grounded),
            ("faithfulness", score.judged),
        ):
            if value is False:
                console.print(f"  [red]failed on {label}")
        if score.judge_reason and score.judged is False:
            console.print(f"  [red]judge:[/] {escape(score.judge_reason)}")
        if score.ungrounded_numbers:
            console.print(
                f"  [red]números sem apoio na fonte:[/] {', '.join(score.ungrounded_numbers)}"
            )


@app.command()
def serve(
    host: str = HostOption,
    port: int = PortOption,
    reload: bool = ReloadOption,
    verbose: bool = VerboseOption,
) -> None:
    """Sobe a API HTTP. Documentação interativa em /docs."""
    setup_logging(verbose=verbose)

    import uvicorn

    console.print(f"[green]API em[/] http://{host}:{port}  ·  docs em http://{host}:{port}/docs")
    # Passed as an import string rather than the object, because --reload needs
    # to re-import the module in a fresh process.
    uvicorn.run("rag_agent.api.app:app", host=host, port=port, reload=reload)


def _render_comparison(diff: Comparison, source: Path) -> None:
    """Show what moved, and what setting moved with it."""
    console.print(f"\n[bold]comparação com[/] {source.name}")

    if diff.settings:
        for name, (before, after) in diff.settings.items():
            console.print(f"  [cyan]{name}[/] {before} → {after}")
    elif diff.baseline_unknown_configuration:
        # Reports written before the configuration was recorded cannot be
        # compared setting by setting. Saying so beats implying nothing moved.
        console.print("  [dim]o relatório antigo não gravou a configuração")

    for name, (before, after) in diff.changed_metrics.items():
        console.print(f"  {name:<20} {before} → {after}")

    if not diff.changed_metrics:
        console.print("  [dim]nenhuma métrica mudou")

    for case in diff.cases:
        if case.change.value in {"corrigido", "quebrado"}:
            cor = "red" if case.is_regression else "green"
            console.print(f"  [{cor}]{case.change.value}[/] {case.case_id}")

    if diff.regressions:
        console.print(f"  [red]{len(diff.regressions)} regressão(ões)")


def _require_index() -> None:
    """Stop early when there is nothing to search: the answer would be useless."""
    if _count_or_exit() == 0:
        console.print(_EMPTY_INDEX_HINT)
        raise typer.Exit(code=1)


def _count_or_exit() -> int:
    """Count indexed chunks, turning an unreachable server into a clean exit."""
    try:
        return count_documents()
    except DatabaseUnavailableError as error:
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
