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
    sync_dataset,
)
from rag_agent.indexing import (
    VectorStoreUnavailableError,
    count_documents,
    describe_location,
    index_documents,
    load_documents,
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
    False,
    "--judge",
    help="Também pede a um modelo que julgue fidelidade e completude. Custa tokens.",
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
    help="Publica o dataset de avaliação no Langfuse e roda experimentos lá.",
)
app.add_typer(dataset_app, name="dataset")

RunNameOption = typer.Option(None, "--name", "-n", help="Nome da execução. O padrão é a data.")


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


@dataset_app.command("run")
def dataset_run(
    name: str | None = RunNameOption,
    judge: bool = JudgeOption,
    verbose: bool = VerboseOption,
) -> None:
    """Roda o dataset como experimento no Langfuse, com os traces e as notas lá."""
    setup_logging(verbose=verbose)
    _require_index()

    settings = get_settings()
    run_name = name or f"{settings.chat_model}-k{settings.retrieval_k}-{_today()}"
    configuration = capture_configuration().to_dict()
    configuration.pop("prompt")

    with console.status(f"[cyan]Rodando o experimento {run_name}..."):
        result = _with_langfuse(
            lambda: run_experiment(
                name=run_name,
                description=f"chunking {settings.chunk_strategy.value}, k={settings.retrieval_k}",
                metadata=configuration,
                with_judge=judge,
            )
        )

    console.print(f"[green]OK[/] experimento [bold]{run_name}[/]")

    url = getattr(result, "dataset_run_url", None)
    if url:
        console.print(f"[dim]{url}")
    console.print("[dim]Compare execuções na aba Datasets do Langfuse.")


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
    console.print(
        f"[bold]índice      [/] {settings.vector_store_mode.value} · {describe_location()}"
    )
    console.print(f"[bold]indexado    [/] [{'green' if total else 'yellow'}]{total} pedaço(s)")


@app.command(name="eval")
def eval_command(
    dataset: Path = DatasetOption,
    limit: int = LimitOption,
    save: bool = SaveOption,
    compare_with: Path | None = CompareOption,
    min_score: float = MinScoreOption,
    max_cost: float = MaxCostOption,
    judge: bool = JudgeOption,
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
            ("citação", score.citation_correct),
            ("fato", score.facts_present),
            ("recusa", score.refusal_correct),
            ("fundamentação", score.grounded),
            ("juiz", score.judged),
        ):
            if value is False:
                console.print(f"  [red]falhou em {label}")
        if score.judge_reason and score.judged is False:
            console.print(f"  [red]juiz:[/] {escape(score.judge_reason)}")
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
