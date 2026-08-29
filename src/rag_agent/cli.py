"""Interface de linha de comando: como um humano usa o sistema.

Comandos:
    rag ingest              processa a pasta data/ e monta o índice
    rag ask "pergunta"      pergunta ao agente
    rag status              mostra o estado do índice
"""

from __future__ import annotations

import logging

# typer transforma cada função decorada em um subcomando do terminal
import typer
# Console = saída colorida que respeita a largura do terminal
from rich.console import Console
# Panel desenha uma moldura em volta do texto
# escape() neutraliza os colchetes do texto: o rich usa [tag] como sintaxe de cor,
# e um trecho de documento contendo "[fonte: x]" seria engolido como se fosse formatação
from rich.markup import escape
from rich.panel import Panel

from langchain_core.messages import AIMessage, HumanMessage

from rag_agent.agent import build_agent, formatar_rastro, perguntar
from rag_agent.config import get_settings
from rag_agent.ingest import load_documents, split_documents
from rag_agent.store import count_documents, index_documents

# add_completion=False remove a opção de autocomplete do shell, que ninguém usa em projeto pequeno
app = typer.Typer(add_completion=False, help="Assistente RAG sobre a documentação do Nimbus.")
console = Console()


def _configurar_log(verboso: bool) -> None:
    """Liga os logs detalhados só quando o usuário pedir com --verbose."""
    # INFO mostra o que cada módulo está fazendo; WARNING só mostra problemas
    logging.basicConfig(
        level=logging.INFO if verboso else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


# @app.command() registra a função como subcomando. O nome vem do nome da função
@app.command()
def ingest(
    # typer.Option cria uma flag; "--verbose/-v" é como o usuário a aciona
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Mostra logs detalhados."),
) -> None:
    """Lê os documentos de data/, quebra em pedaços e indexa no banco vetorial."""
    _configurar_log(verbose)
    settings = get_settings()

    # status() mostra um spinner enquanto a operação demora
    with console.status("[cyan]Carregando documentos..."):
        documentos = load_documents(settings.data_dir)

    # Pasta vazia não é erro de programa, é aviso ao usuário: sair com código 1
    if not documentos:
        console.print(f"[yellow]Nenhum documento encontrado em {settings.data_dir}")
        raise typer.Exit(code=1)

    console.print(f"[green]OK[/] {len(documentos)} documento(s) carregado(s)")

    pedacos = split_documents(
        documentos,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    console.print(f"[green]OK[/] {len(pedacos)} pedaço(s) gerado(s)")

    # Esta é a etapa que gasta API: avisar o usuário com o spinner
    with console.status("[cyan]Gerando embeddings e indexando..."):
        total = index_documents(pedacos)

    console.print(f"[green]OK[/] {total} pedaço(s) indexado(s) em {settings.vector_store_dir}")


@app.command()
def ask(
    # typer.Argument (sem "--") é posicional: o usuário digita direto após o comando
    pergunta: str = typer.Argument(..., help="A pergunta em linguagem natural."),
    trace: bool = typer.Option(False, "--trace", "-t", help="Mostra o raciocínio do agente."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Mostra logs detalhados."),
) -> None:
    """Pergunta ao agente, que decide sozinho quais ferramentas usar."""
    _configurar_log(verbose)

    # Índice vazio produziria uma resposta inútil: melhor avisar e ensinar o próximo passo
    if count_documents() == 0:
        console.print("[yellow]O índice está vazio. Rode primeiro:[/] rag ingest")
        raise typer.Exit(code=1)

    with console.status("[cyan]Pensando..."):
        resultado = perguntar(pergunta)

    # --trace imprime o rastro ANTES da resposta, na ordem em que aconteceu
    if trace:
        rastro = escape(formatar_rastro(resultado["mensagens"]))
        console.print(Panel(rastro, title="raciocínio", border_style="dim"))

    console.print(Panel(escape(str(resultado["resposta"])), title="resposta", border_style="green"))

    # Lista das ferramentas usadas, para o usuário entender de onde veio a resposta
    usadas = [f["nome"] for f in resultado["ferramentas"]]
    if usadas:
        console.print(f"[dim]ferramentas usadas: {', '.join(usadas)}")


@app.command()
def chat(
    trace: bool = typer.Option(False, "--trace", "-t", help="Mostra as ferramentas usadas."),
) -> None:
    """Conversa contínua com o agente, com memória entre as perguntas."""
    if count_documents() == 0:
        console.print("[yellow]O índice está vazio. Rode primeiro:[/] rag ingest")
        raise typer.Exit(code=1)

    # Monta o agente UMA vez e reusa: reconstruir a cada pergunta seria desperdício
    agente = build_agent()
    # O modelo não tem memória própria. Esta lista É a memória: reenviamos ela inteira
    mensagens: list = []

    console.print(Panel(
        "Converse com o agente. Ele lembra do que já foi dito.\n"
        "Digite [bold]sair[/] para encerrar.",
        title="modo conversa", border_style="cyan",
    ))

    while True:
        try:
            pergunta = console.input("\n[bold cyan]você[/] > ").strip()
        # Ctrl+C ou fim da entrada encerram sem stack trace feio
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]até mais.")
            break

        # Enter vazio: não gastar uma chamada de API à toa
        if not pergunta:
            continue
        if pergunta.lower() in {"sair", "exit", "quit"}:
            console.print("[dim]até mais.")
            break

        # Acrescenta a nova pergunta ao histórico acumulado
        mensagens.append(HumanMessage(pergunta))

        with console.status("[cyan]pensando..."):
            estado = agente.invoke({"messages": mensagens})

        # O estado devolvido JÁ contém todo o histórico + as novas mensagens.
        # Substituir a lista inteira é o que faz a memória funcionar na próxima volta
        mensagens = estado["messages"]

        console.print(f"[bold green]agente[/] > {escape(str(mensagens[-1].content))}")

        if trace:
            usadas = [
                c["name"]
                for m in mensagens
                if isinstance(m, AIMessage) and m.tool_calls
                for c in m.tool_calls
            ]
            console.print(f"[dim]ferramentas: {', '.join(usadas) or 'nenhuma'}")


@app.command()
def status() -> None:
    """Mostra a configuração ativa e quantos pedaços estão indexados."""
    settings = get_settings()
    total = count_documents()

    console.print(f"[bold]modelo      [/] {settings.chat_model}")
    console.print(f"[bold]embeddings  [/] {settings.embedding_model}")
    console.print(f"[bold]chunk       [/] {settings.chunk_size} / overlap {settings.chunk_overlap}")
    console.print(f"[bold]documentos  [/] {settings.data_dir}")
    console.print(f"[bold]índice      [/] {settings.vector_store_dir}")
    # Zero pedaços em amarelo chama atenção para o que fazer em seguida
    cor = "green" if total else "yellow"
    console.print(f"[bold]indexado    [/] [{cor}]{total} pedaço(s)")


# Só roda o app quando o arquivo é executado direto, não quando é importado
if __name__ == "__main__":
    app()
