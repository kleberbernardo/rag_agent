"""Command line interface: presentation only, no domain logic.

rag ingest              build the index from data/
rag ask "question"      ask the agent once
rag chat                talk to the agent with memory
rag status              inspect the current configuration and index
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from rag_agent.agent import ChatSession, ask, format_trace
from rag_agent.config import get_settings
from rag_agent.indexing import count_documents, index_documents, load_documents, split_documents
from rag_agent.logging_setup import setup_logging
from rag_agent.types import AnswerResult

app = typer.Typer(
    add_completion=False,
    help="Agente RAG sobre a sua própria base de documentos.",
)
console = Console()

_EMPTY_INDEX_HINT = "[yellow]O índice está vazio. Rode primeiro:[/] rag ingest"
_EXIT_WORDS = frozenset({"sair", "exit", "quit"})

VerboseOption = typer.Option(False, "--verbose", "-v", help="Mostra logs detalhados.")
TraceOption = typer.Option(False, "--trace", "-t", help="Mostra o raciocínio do agente.")


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

    console.print(f"[green]OK[/] {total} pedaço(s) indexado(s) em {settings.vector_store_dir}")


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
            break

        with console.status("[cyan]pensando..."):
            result = session.send(question)

        console.print(f"[bold green]agente[/] > {escape(result.answer)}")
        if trace:
            console.print(f"[dim]ferramentas: {', '.join(result.tool_names) or 'nenhuma'}")


@app.command()
def status() -> None:
    """Mostra a configuração ativa e quantos pedaços estão indexados."""
    settings = get_settings()
    total = count_documents()

    console.print(f"[bold]modelo      [/] {settings.chat_model}")
    console.print(f"[bold]embeddings  [/] {settings.embedding_model}")
    console.print(f"[bold]chunk       [/] {settings.chunk_size} / overlap {settings.chunk_overlap}")
    console.print(f"[bold]domínio     [/] {settings.knowledge_domain}")
    console.print(f"[bold]documentos  [/] {settings.data_dir}")
    console.print(f"[bold]índice      [/] {settings.vector_store_dir}")
    console.print(f"[bold]indexado    [/] [{'green' if total else 'yellow'}]{total} pedaço(s)")


def _require_index() -> None:
    """Stop early when there is nothing to search: the answer would be useless."""
    if count_documents() == 0:
        console.print(_EMPTY_INDEX_HINT)
        raise typer.Exit(code=1)


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


if __name__ == "__main__":
    app()
