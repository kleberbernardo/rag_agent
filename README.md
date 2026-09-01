# RAG Agent

[![CI](https://github.com/kleberbernardo/rag_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/kleberbernardo/rag_agent/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A command-line AI agent that answers questions about your own documents.

Point it at a folder of files, run the ingestion, and ask questions in plain
language. The agent retrieves the relevant passages before answering and cites
the file it took each answer from. When the answer is not in your documents, it
says so instead of inventing one.

- **Grounded**: answers come from retrieved passages, never from model memory.
- **Cited**: every answer names its source file.
- **Agentic**: the model decides when to search, can search again with
  different terms, and can reach for other tools.
- **One database**: Postgres with pgvector holds the embeddings and answers
  keyword search over the same rows, so a chunk and its metadata are written
  in a single transaction and cannot drift apart.
- **Measured**: every answer reports its latency, token usage and estimated
  cost, with optional full tracing to Langfuse.
- **Domain-agnostic**: the subject lives in configuration, not in code. Swap
  the folder, change one variable, re-ingest.
- **Evaluated**: 29 graded questions, including ones the corpus cannot answer.
  Currently 100%, with the caveat that one of the six metrics is model-graded
  and drifts.
- **Two interfaces**: a CLI and an HTTP API over the same service layer, both
  in one container.

---

## Architecture

Two phases that never run at the same time, and two interfaces over one
service layer.

```
INGESTION  ·  offline, `rag ingest`

   data/*.pdf ──► loader ──► splitter ──► embeddings ──► Postgres
                  pdf, md    per article    OpenAI       pgvector
                  txt, rst   Art. 1, 2…                  + full text


QUERY  ·  online

   CLI  rag ask ───┐
                   ├──► service ──► agent ──┬──► search_documentation ──► Postgres
   API  POST /ask ─┘                  ▲     │
                                      │     └──► calculate
                                      └─────────┘  the result comes back

                   answer + source + latency · tokens · cost
                                       │
                            ┌──────────┴──────────┐
                            ▼                     ▼
                      Langfuse trace         rag eval · 29 cases · 97%
```

The loop separates this from a plain pipeline. A pipeline retrieves once and
answers. Here the model may skip retrieval, retry with different terms, or
chain a second tool, and it stops only when it writes prose instead of calling
something.

Both interfaces sit on `service`, so neither holds orchestration of its own.
The CLI and the HTTP layer translate their input into a call and the result
back out, and nothing else.

| Layer | Module | Responsibility |
|---|---|---|
| Interfaces | `cli.py`, `api/` | Translate in and out. No decisions. |
| Orchestration | `agent/` | Build the graph, run a turn, measure it. |
| Capabilities | `tools/` | What the model may call. |
| Retrieval | `indexing/` | Load, split, embed, search by meaning and by word. |
| Providers | `providers.py` | The only place OpenAI appears. |
| Behaviour | `prompts/` | The rules, fetched from Langfuse or read from `templates.py`. |
| Measurement | `evaluation/` | Grade the agent, locally or on the platform. |

---

## The agent loop

`create_agent` builds a LangGraph state graph and returns it compiled. The
project never imports `langgraph` itself, and the graph is not hand-written:
it has three nodes and one conditional edge.

```
   __start__
       │
       ▼
   ┌───────┐
   │ model │ ◄─────────┐
   └───┬───┘           │
       │ conditional   │
   ┌───┴────┐          │
   ▼        ▼          │
 tools   __end__       │
   │                   │
   └───────────────────┘
```

The conditional edge carries the whole idea. After the model speaks, the graph
asks whether it requested a tool:

- **yes** → run `tools`, feed the output back into `model`
- **no** → `__end__`, the answer is final

That cycle lets the agent search, read what came back, and decide again. Without it the flow is linear: retrieve once, answer, stop.

The loop is capped two ways, and both caps exist because of the same
question: one the corpus cannot answer.

`MAX_SEARCHES_PER_TURN` stops the searching. A vector search always returns its
`k` nearest chunks, however far they sit, so it can never report finding
nothing. The agent therefore sees results on every attempt and rewords the
query indefinitely. Past the budget the tool answers with an instruction to
conclude, and the agent says it did not find the subject, which is the truthful
outcome.

A distance threshold would be the obvious fix and does not work here. Measured
on this corpus, the worst valid question scores 0.972 and the best invalid one
0.840: the ranges overlap, so any cut rejects good questions or accepts bad
ones.

Ten steps on the graph is the second cap, and the safety net behind the first.

## Technologies

| Layer | Used |
|---|---|
| Orchestration | LangChain 1.x and LangGraph 1.x, through `create_agent` |
| Model | OpenAI: `gpt-4o-mini`, `text-embedding-3-small`, reached through `langchain-openai` |
| Vector store | Postgres 17 with pgvector, and its full text search |
| Database access | `langchain-postgres`, SQLAlchemy 2, `psycopg` 3 |
| Chunking | `langchain-text-splitters` |
| Reranking | Optional cross-encoder, `BAAI/bge-reranker-v2-m3`, through `sentence-transformers` |
| Guardrails | LLM Guard: prompt injection, secrets, anonymisation |
| HTTP | FastAPI, Uvicorn |
| Sessions | In process by default, Redis when shared across replicas |
| CLI | Typer, Rich |
| Configuration | Pydantic 2, Pydantic Settings, python-dotenv |
| Documents | pypdf |
| Observability | Langfuse, optional |
| Quality | pytest, pytest-cov, httpx, ruff, mypy |
| Infrastructure | Docker, Compose, GitHub Actions |

Python 3.12 or newer. Every OpenAI import lives in `providers.py`, which is the
only file a provider swap rewrites.

## Concepts

| Concept | Where it lives |
|---|---|
| Retrieval-augmented generation | The whole project |
| Embeddings and semantic search | `indexing/vector_store.py` |
| Chunking | Two strategies: by character, by article |
| Chunk overlap | 200 characters, so an idea survives a boundary |
| Tool calling | `tools/`, where the model picks what to run |
| Agent loop | The conditional edge above |
| Grounding and source citation | Every answer names its document |
| Idempotent ingestion | A chunk's id is a hash of its content |
| Evaluation | 29 cases, five deterministic metrics |
| Groundedness | Every number has to come from what was read |
| LLMOps | Latency, tokens, cost, tracing |
| Sandboxing | The calculator validates by AST before evaluating |
| Layered architecture | Interfaces on top of one service layer |
| Configuration by environment | Every setting read from the environment |

---

## Installation

Requires Python 3.12+ and an OpenAI API key.

**1. Create the virtual environment and activate it**

```powershell
# Windows (PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

```bash
# Linux / macOS
python -m venv .venv
source .venv/bin/activate
```

Your prompt now starts with `(.venv)`. That is how you know it worked.

**2. Install the project**

```bash
pip install -e ".[dev]"
```

The `-e` flag means code changes take effect immediately, and the install
registers the `rag` command.

**3. Set your API key**

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Then edit `.env`:

```
OPENAI_API_KEY=sk-...
```

---

## Running the commands

> **The `rag` command only exists while the virtual environment is active.**
> Activation lasts for that terminal window only. Open a new one and you have
> to activate again. This is the single most common reason `rag` "does not
> work".

Every session starts like this:

```powershell
.\.venv\Scripts\Activate.ps1     # Windows; source .venv/bin/activate elsewhere
$env:PYTHONIOENCODING='utf-8'    # Windows only, keeps accented output intact
```

`rag: command not found` (or `The term 'rag' is not recognized`) always means
the environment is not active. Two ways out:

```powershell
.\.venv\Scripts\Activate.ps1     # activate, then use `rag ...`
.\.venv\Scripts\rag.exe chat     # or call the executable directly, no activation
```

If PowerShell refuses to run the activation script with *"running scripts is
disabled on this system"*, allow it once for your user:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Never installed the package at all? `python main.py chat` works from the
project root without the `rag` command.

---

## Commands

Nine commands. Three of them are what you use daily.

| Command | What it does | Flags |
|---|---|---|
| `rag ingest` | Read `data/`, split it, index it. Run it once, and again when the documents change. | `--reset`, `-v` |
| `rag ask "..."` | One question. | `--trace`, `-v` |
| `rag chat` | A conversation with memory. | `--trace`, `-v` |
| `rag status` | The active configuration and how many chunks are indexed. | |
| `rag sources` | List the indexed documents, or drop one of them from the index. | `--remove <file>`, `--yes` |
| `rag eval` | Grade the agent against the 29 questions. | See the table below |
| `rag serve` | Start the HTTP API. | `--host`, `--port`, `--workers`, `--reload`, `-v` |
| `rag prompt show` \| `push` | Read the prompt in force; publish the local ones. | `--message`, `-v` |
| `rag dataset push` | Upload the evaluation dataset to Langfuse. | `--dataset`, `-v` |

`--verbose` and `-v` mean the same thing on every command that takes it, and
raise the log level for that run.

### `rag eval` in full

One command. Nothing to choose about where it runs:

```bash
rag eval
```

| With Langfuse configured | Without |
|---|---|
| Questions come from the dataset there | Questions come from `evals/dataset.json` |
| Scores go back, one per metric per question | A report is written to `evals/results/` |

Either way the agent and the metrics run on this machine. No platform executes
your application: Langfuse's own documentation is explicit that its evaluators
"score the data already recorded on your traces" and "never re-execute your
application". That division is the standard one, and it is what the RAGAS and
Langfuse integration describes: the framework computes the metric, the platform
stores the score next to the trace that produced the answer.

What happens on one run:

```
1. read the 29 questions          Langfuse, or the file
2. answer each one                this machine, always
3. score six metrics              this machine, always
4. send the scores                Langfuse, one per metric per question
5. print the table                this terminal, always
```

| Flag | Effect |
|---|---|
| `--no-judge` | Skip `faithfulness`, the only metric that costs tokens to compute |
| `--limit N` | Only the first N questions |
| `--min-score 0.9` | Exit non-zero below this |
| `--max-cost 0.05` | Exit non-zero above this |
| `--name` | Name the run on the platform |
| `--compare <report>` | Diff against a previous local report |

### Reading it in Langfuse

Three places hold the same run, at different resolutions:

| Where | What you see |
|---|---|
| **Experiments** | One row per question, the metrics as columns. Start here. |
| **Scores** | One row per metric per question, raw. 29 × 6 rows, not a summary. |
| **Tracing** | One question in full: the search, the passages, the tool calls, the cost. |

The **Evaluators** menu stays empty on purpose. It holds judges that Langfuse
runs on its own servers over live traffic, configured through a form. This
project's judge lives in `evaluation/judge.py`, so its rubric is versioned,
testable and readable in the repository, and it runs offline. The two are
different features that share a word.

---

## Usage

All commands below assume the environment is active.

### 1. Add your documents

Drop files into `data/`. Supported: `.md`, `.txt`, `.markdown`, `.rst` and
`.pdf`. Subfolders are scanned recursively; anything else is skipped.

The repository ships with a real corpus so you can try it immediately: three
consolidated resolutions from the CVM, the Brazilian securities regulator.
204 pages covering suitability, disclosure of material information and public
offerings. Provenance is recorded in `docs/knowledge-base-sources.md`.

Nothing in the code depends on them. To use your own, empty `data/`, set
`KNOWLEDGE_DOMAIN` in `.env` and run `rag ingest --reset`.

### 2. Build the index

```bash
rag ingest
rag ingest --verbose
```

Run this once, and again whenever the documents change. Ingestion is
idempotent: running it twice updates the same records instead of duplicating
them.

### 3. Ask

```bash
rag ask "o que e o dever de verificacao da adequacao dos produtos?"
rag ask "qual o percentual maximo do lote suplementar?" --trace
```

`--trace` prints the agent's reasoning: which tools it chose, with which
arguments, and what each returned.

```
$ rag ask "qual o percentual maximo do lote suplementar numa oferta publica?
           numa oferta de R$ 500 milhoes, quanto isso representa?" --trace

╭─ raciocínio ──────────────────────────────────────────────────╮
│ [AGENTE decide] chamar search_documentation(...)              │
│ [AGENTE decide] chamar calculate({'expression': '5e8 * 0.15'})│
│ [FERRAMENTA search_documentation] -> a observância do limi... │
│ [FERRAMENTA calculate] -> 75000000                            │
╰───────────────────────────────────────────────────────────────╯
╭─ resposta ────────────────────────────────────────────────────╮
│ O percentual máximo do lote suplementar é de 15% da           │
│ quantidade inicialmente ofertada. Em uma oferta de R$ 500     │
│ milhões, isso representa R$ 75 milhões.                       │
│ (fonte: cvm-resolucao-160-ofertas-publicas.pdf)               │
╰───────────────────────────────────────────────────────────────╯
ferramentas usadas: search_documentation, calculate
4.82s · 1788 tokens (1635 in / 153 out) · 2 tool call(s) · ~US$ 0.00034
```

Every answer closes with what it cost: wall-clock latency, tokens split
between input and output, how many tools ran, and an estimated price. It is
measured locally from the provider's own usage reporting, with no account and
no external service. A model with no listed price shows no estimate rather than a
confident wrong number.

The agent did not do the arithmetic itself. It delegated the multiplication
to the calculator, and cited the page it took the limit from.

Citations reach the article, not just the file, because article-based chunking
records which `Art. N` each passage came from:

```
$ rag ask "qual o prazo para atendimento das primeiras exigências?"

╭─ resposta ─────────────────────────────────────────────────────────╮
│ O prazo para o atendimento das primeiras exigências é de 40        │
│ (quarenta) dias úteis, contados a partir da emissão de ofício com  │
│ as exigências ao requerente. Esse prazo pode ser prorrogado uma    │
│ única vez, por um período não superior a 20 (vinte) dias úteis,    │
│ mediante pedido fundamentado. Após o cumprimento das exigências,   │
│ a SRE tem 10 (dez) dias úteis para se manifestar sobre o pedido    │
│ de registro.                                                       │
│ (fonte: cvm-resolucao-160-ofertas-publicas.pdf, Art. 38)           │
╰────────────────────────────────────────────────────────────────────╯
ferramentas usadas: search_documentation
4.88s · 4115 tokens (3974 in / 141 out) · 1 tool call(s) · ~US$ 0.00068
```

That single article carries five different deadlines across its paragraphs.
Cutting every 1000 characters used to separate them, and the agent answered
with the neighbouring one. `CHUNK_STRATEGY=articles` fixed that.

### 4. Or hold a conversation

```bash
rag chat
rag chat --trace        # adds the tools used and the cost of each turn
```

Keeps context between turns, so follow-up questions work without repeating the
subject. Exit with `sair`, `exit` or `Ctrl+C`. Every command also takes
`--verbose`, which turns on the log of what each module is doing.

```
você > o que caracteriza uma informacao relevante?
agente > É qualquer decisão ou fato que possa influir de modo ponderável
         na cotação dos valores mobiliários...
         (fonte: cvm-resolucao-44-informacoes-relevantes.pdf)

você > e quem tem o dever de divulgar?     ← no need to restate the subject
agente > O Diretor de Relações com Investidores...
         (fonte: cvm-resolucao-44-informacoes-relevantes.pdf)

você > sair
```

### Diagnostics

```bash
rag status
```

Shows the active configuration and how many chunks are indexed. Run this first
whenever something looks wrong.

---

## Configuration

Everything lives in `.env`. Copy `.env.example` and edit. Values are validated
at boot, so an invalid setting stops the program immediately with a clear
message rather than failing mid-query.

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | none | **Required.** |
| `CHAT_MODEL` | `gpt-4o-mini` | Model that reasons and picks tools. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Model that turns text into vectors. |
| `TEMPERATURE` | `0.0` | `0` is deterministic, the right setting for grounded answers. |
| `CHUNK_STRATEGY` | `articles` | `articles` gives each `Art. N` its own chunk; `characters` cuts by length. |
| `CHUNK_SIZE` | `1000` | Max characters per chunk. |
| `ARTICLE_MAX_CHARS` | `4000` | Cap above which a single article is split further. |
| `CHUNK_OVERLAP` | `200` | Characters repeated between neighbouring chunks. |
| `SEARCH_STRATEGY` | `hybrid` | `hybrid` fuses the database's full text search with the embedding; `vector` uses the embedding alone. |
| `RERANK_STRATEGY` | `none` | `cross_encoder` adds a second pass that reorders what was retrieved. Needs the `rerank` extra. |
| `RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | The cross-encoder to load. Multilingual, open source, runs locally. |
| `RERANK_CANDIDATES` | `24` | How many candidates the reranker reads. Every one is a model pass, so this is the latency knob. |
| `RATE_LIMIT` | `60/minute` | Ceiling per caller. Empty disables it. |
| `API_WORKERS` | `1` | Uvicorn processes. One serialises every request. |
| `RETRIEVAL_K` | `8` | Passages retrieved per question. |
| `MAX_SEARCHES_PER_TURN` | `3` | How many times the agent may search one question. |
| `KNOWLEDGE_DOMAIN` | generic | What the corpus is about. Injected into the system prompt and the search tool description. |
| `DATA_DIR` | `data/` | Where your documents live. |
| `LOG_DIR` | `logs/` | Where the log file is written. |
| `DATABASE_URL` | `postgresql+psycopg://rag:rag@localhost:5432/rag` | Where the index lives. The driver is named because SQLAlchemy defaults to psycopg2. |
| `DATABASE_POOL_SIZE` | `5` | Connections held open per process. Replicas multiply this. |
| `DATABASE_MAX_OVERFLOW` | `10` | Extra connections allowed above the pool under load. |
| `EMBEDDING_DIMENSIONS` | `1536` | Width of the embedding column. Must match the model. |
| `COLLECTION_NAME` | `rag_agent_docs` | Collection name inside the store. |
| `LANGFUSE_PUBLIC_KEY` | none | Optional. Enables tracing when set together with the secret key. |
| `LANGFUSE_SECRET_KEY` | none | Optional. See [Observability](#observability). |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse region, e.g. `https://us.cloud.langfuse.com`. |
| `PROMPT_LABEL` | `production` | Which published prompt version the agent picks up. |
| `PROMPT_CACHE_SECONDS` | `60` | How long a fetched prompt is reused. |
| `SESSION_BACKEND` | `memory` | `memory` keeps conversations in the process; `redis` shares them. |
| `REDIS_URL` | `redis://localhost:6379/0` | Where Redis lives, in `redis` mode. |
| `SESSION_TTL_SECONDS` | `3600` | How long an idle conversation survives. |
| `API_KEY` | none | Set it and every request needs the `X-API-Key` header. |
| `MAX_RETRIES` | `3` | Retries on a rate-limited or unavailable provider. |
| `REQUEST_TIMEOUT_SECONDS` | `60` | Ceiling on one provider call. |

---

## How it works

The system has two phases that never run at the same time.

### Phase 1: ingestion (offline)

```
data/*  ──▶  load  ──▶  split  ──▶  embed  ──▶  Postgres
          (loader)   (splitter)  (providers)  (vector_store)
```

**Load**. Each file becomes a `Document` carrying its filename as metadata.
The final answer cites its source from that metadata. PDFs become one
document per page, so a citation can point at a page number.

**Split**. Two strategies, chosen by `CHUNK_STRATEGY`.

`characters` cuts every `CHUNK_SIZE` characters, breaking at paragraph
boundaries first, then lines, sentences and words. Chunks overlap by
`CHUNK_OVERLAP` characters so an idea falling across a boundary survives whole
in at least one of them.

`articles` gives each `Art. N` its own chunk. Legal and regulatory texts are
already divided by their author, and cutting every 1000 characters separates a
rule from the exception that qualifies it. The shipped corpus has one article
carrying five different deadlines across its paragraphs. Only a capitalised
`Art.` opens an article; lowercase `art. 36` is a cross-reference inside a
sentence, and this corpus has 138 of those against 106 real headings.

It is adaptive: a source with fewer than three headings falls back to
characters, so a plain README in the folder is unharmed. PDF pages are joined
before splitting, because an article routinely spans a page break. Articles
over `ARTICLE_MAX_CHARS` are split further, because annexes carry no headings
and one arrived as a single 148,000-character block.

Measured on the shipped corpus: **93% by characters, 97% by articles.**

**Embed**. Each chunk is sent to the embedding model and comes back as a
vector: a list of numbers positioning that text in semantic space. Chunks that
mean similar things land near each other.

**Store**. Vectors are written to Postgres. Each chunk gets an id derived from
a hash of its source and content, so re-ingestion overwrites instead of
duplicating. That is also what makes ingestion safe to retry from a queue,
where the same message can be delivered more than once.

The store runs in one of two modes, chosen by `VECTOR_STORE_MODE`:

Postgres is the only mode. An embedded file would be one less thing to run,
and it would also be a second storage engine to keep behaving like the first,
which is a cost paid on every change to retrieval for a convenience that ends
the moment the corpus is shared.

An unreachable database fails with a message that names the address it tried
and the command that brings it up, rather than a driver stack trace. The
password is removed from every rendering of the URL, including that message.

### Why Postgres

| | |
|---|---|
| **Two retrievers, one store** | The vectors and the text sit in the same rows, so keyword search needs no second system and no copy that can go stale. |
| **One transaction** | A chunk, its metadata and its vector are written together or not at all. |
| **Already there** | Most organisations run Postgres. This adds an extension, not a database to operate. |
| **Managed everywhere** | RDS, Cloud SQL, Supabase, Neon all ship pgvector. |
| **Debuggable** | The index is inspectable with `SELECT`, not through a proprietary API. |

Two indexes are built after the first write, since neither can exist before
the tables do. `HNSW` on the vector column is the approximate nearest
neighbour index; without it pgvector is exact, which is correct and reads
every row. `GIN` on the text expression is what keeps keyword search from
parsing every stored document on every query. Both are the difference between
a corpus of hundreds and one of millions.

The ceiling is somewhere above ten million vectors, or heavy metadata
filtering at high query rates. Past that the answer is a dedicated engine such
as Qdrant, and the change is one class: nothing in the fusion, the agent or
the evaluation knows which store answered.

### Phase 2: query (online)

```
question ──▶ agent decides ──▶ runs a tool ──▶ reads the result
                  ▲                                    │
                  └────────── loops if needed ◀────────┘
                                     │
                                     ▼
                          answer, with its source cited
```

The question is embedded by the **same model** used during ingestion, and the
store returns the nearest chunks. This is why "what does the cheapest tier
cost" finds the right passage even when neither "cheapest" nor "tier" appears
in the text. Matching happens on meaning, not on words.

A search is two stages, and only the first always runs:

```
question ──▶ retrieval ──▶ candidates ──▶ [reranking] ──▶ passages
             wide, cheap                   narrow, off by default
```

Retrieval decides what is in the pool and is judged on whether the answer is
there at all. Reranking decides what comes out of it and is judged on whether
the best of them is on top. With no reranker the pool is the answer, so it is
retrieved at exactly the width asked for. See
[Reranking](#reranking) for why the second stage is off here.

> Change `EMBEDDING_MODEL` and you must run `rag ingest --reset`, and set
> `EMBEDDING_DIMENSIONS` to match. Vectors from different models are neither
> comparable nor the same width.

### Why an agent, not a plain pipeline

A plain RAG pipeline always retrieves exactly once, then answers. This one lets
the model decide:

| Plain RAG | This project |
|---|---|
| Always retrieves once | Decides whether to retrieve at all |
| One query per question | Can retry with different search terms |
| Retrieval only | Chooses among several tools |

The loop is: the model reads the question, may emit a tool call, the tool runs,
the result comes back as a message, and the model reads it and decides again.
It ends when the model stops calling tools and writes prose.

### Tools

A tool is a plain Python function the model may call. The model never sees the
body, only the name, the signature and the docstring. **The docstring is the
contract**: it is how the model decides when the tool applies.

- `search_documentation`: semantic search over the indexed chunks.
- `calculate`: a safe arithmetic evaluator. Language models are unreliable at
  arithmetic, so anything numeric is delegated here. Expressions are parsed
  into a syntax tree and checked against an allow-list, so a model-authored
  string can never become arbitrary code execution.

To add one: write the function with the `@tool` decorator in its own module
under `tools/`, then register it in `build_tools()`. It is a function rather
than a constant because the search tool's description is rendered at call time
from `KNOWLEDGE_DOMAIN`.

### Behaviour

The agent's rules live in `prompts.py`: always retrieve before answering
about the documents, answer only from retrieved passages, admit when something
is missing, always cite the source, and never do arithmetic mentally. Editing
that file is how you change how the agent behaves.

---

## Project structure

```
src/rag_agent/
├── config.py          settings, read from the environment and validated at boot
├── types.py           AnswerResult, SearchHit, ToolCall, RunMetrics
├── providers.py       LLM and embedding clients, the only place OpenAI appears
├── cli.py             presentation only, no domain logic
│
├── prompts/           the instructions, and where they are read from
│   ├── __init__.py        fetch from Langfuse, render, fall back to the text
│   └── templates.py       the text itself, and nothing else
│
├── observability/     what the run did, what it cost, and writing it down
│   ├── tracing.py         Langfuse: traces, scores, prompt registry
│   ├── pricing.py         token prices, dated
│   └── logging_setup.py   console and file
│
├── indexing/          loader · splitter · vector_store · hybrid
├── tools/             one module per tool, registered in build_tools()
├── agent/             service (build + orchestration) · trace
├── api/               routes · schemas · sessions · security · feedback
└── evaluation/        dataset · metrics · runner · comparison · configuration
```

Four loose modules and seven packages. The four are the ones every layer
reaches for and none of them owns: settings, domain types, the provider
boundary, and the terminal.

Only three directories, and each earns it: `indexing/` grows with every new
file format, `tools/` with every new tool, `agent/` holds the orchestration.
Everything else is a single module.

| To change... | Edit |
|---|---|
| The knowledge base | `data/`, then `rag ingest` |
| How the agent behaves | Langfuse, or `prompts/templates.py` as the fallback |
| Add a tool | `tools/` |
| Chunking or retrieval | `.env` |
| The model provider | `providers.py` |
| Token prices | `observability/pricing.py` |
| Add an endpoint | `api/routes.py` |

Interfaces stay thin because orchestration lives in `agent/service.py`. Adding
an HTTP API or a bot means wrapping that service, not rewriting it.

---

## HTTP API

The same agent behind an HTTP interface. The endpoints call `agent.service`,
the same orchestration the CLI calls, so this layer translates requests and
results and holds no logic of its own.

```bash
rag serve                          # http://127.0.0.1:8080
rag serve --host 0.0.0.0 --port 80
rag serve --reload                 # development
```

Interactive documentation, generated from the schemas, at `/docs`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/ask` | One question, no memory |
| `POST` | `/chat` | A question inside a conversation |
| `DELETE` | `/chat/{session_id}` | Forget a conversation |
| `POST` | `/feedback` | Record what someone thought of an answer |
| `GET` | `/health` | Liveness plus the indexed chunk count |
| `GET` | `/status` | The active configuration |

```bash
curl -X POST localhost:8080/ask   -H "Content-Type: application/json"   -d '{"question": "qual o percentual maximo do lote suplementar?"}'
```

```json
{
  "answer": "O percentual máximo do lote suplementar não pode ultrapassar 15%...",
  "sources": ["cvm-resolucao-160-ofertas-publicas.pdf"],
  "tools_used": [{"name": "search_documentation", "arguments": {...}}],
  "metrics": {
    "latency_seconds": 9.05,
    "total_tokens": 2949,
    "tool_calls": 1,
    "model": "gpt-4o-mini",
    "estimated_cost_usd": 0.00047
  },
  "session_id": null,
  "trace": null
}
```

Every answer carries what it cost, the same numbers the CLI prints. Add
`"trace": true` to the body to get the reasoning trail as well.

### Conversations

`POST /chat` without a `session_id` opens one and returns its id. Send that id
back to continue:

```bash
curl -X POST localhost:8080/chat -H "Content-Type: application/json"   -d '{"question": "o que caracteriza uma informação relevante?"}'
# -> {"session_id": "97c93e1d...", ...}

curl -X POST localhost:8080/chat -H "Content-Type: application/json"   -d '{"question": "e quem deve divulgar?", "session_id": "97c93e1d..."}'
```

**Where conversations live** depends on `SESSION_BACKEND`.

`memory` is the default and needs nothing running. Conversations belong to the
process that served them, and the store caps at 100 and evicts the oldest,
because each holds its whole message history and an unbounded dictionary is a
memory leak with a friendly name.

`redis` is what makes the service horizontally scalable. A conversation opened
against one replica is readable by the next, it outlives a restart, and Redis
expires it after `SESSION_TTL_SECONDS` so an abandoned one does not occupy
memory forever. `docker compose up` runs this mode.

Only the messages are stored, as JSON. The agent graph holds closures that
cannot be serialised, and it does not need to be: it is rebuilt from
configuration on every request. A conversation written by one deployment
therefore stays readable by the next.

### Authentication

The API is open with no `API_KEY` configured, which keeps `rag serve` working on
a laptop. Set one and every endpoint requires it:

```bash
export API_KEY=$(openssl rand -hex 32)
curl -H "X-API-Key: $API_KEY" localhost:8080/health
```

A missing or wrong key returns `401` naming the header to send. The comparison
uses `hmac.compare_digest` rather than `==`, because a plain comparison returns
as soon as two characters differ, and that timing difference is enough to guess
a key one character at a time.

It is deliberately not an identity system. There are no users, no scopes and no
rotation: anything beyond one shared secret belongs to whatever issues the
tokens, in front of this service.

### Provider failures

A rate-limited or briefly unavailable model is a normal condition, not
something to hand back to the caller. `MAX_RETRIES` retries with backoff and
`REQUEST_TIMEOUT_SECONDS` caps a single call, both applied to the chat model
and to the embeddings.

### Failure modes

| Situation | Response |
|---|---|
| Empty index | `503` naming the ingestion step |
| Postgres unreachable | `/ready` answers `503`; `/health` stays `200` |
| Past the rate limit | `429` with `Retry-After` |
| Malformed body | `422` from the schema |
| Missing or wrong API key | `401`, when `API_KEY` is set |
| Unknown session on delete | `404` |

An unknown `session_id` on `POST /chat` opens a new conversation rather than
failing: a client holding an id from before a restart should keep working.

### LangSmith

LangChain instruments itself, so LangSmith needs no code here at all:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=lsv2_...
```

Langfuse is the default because it is open source, self-hostable and
independent of the framework, while LangSmith is easier to switch on and bound
more tightly to LangChain. Use one or the other: sending the same run to two
platforms means two places to look at the same data.

---

## Prompt management

The prompt decides how the agent behaves, and it changes far more often than
the code around it. Kept as a string in the source, every wording change costs
a commit, a build and a deploy, and no record survives of which text produced
which score.

Published to Langfuse, it becomes a versioned asset:

```bash
rag prompt push -m "regra nova sobre citação"   # publish under the label
rag prompt show                                 # what is in force, and where from
```

```
$ rag prompt show
origem       Langfuse v1
label        production
domínio      regulacao do mercado de capitais brasileiro (resolucoes da CVM)
╭─ system ────────────────────────────────────────────────────╮
│ Você é um assistente especializado em regulacao do mercado  │
│ de capitais brasileiro (resolucoes da CVM).                 │
...
```

Editing the text in the Langfuse UI and moving the `production` label is how a
new version reaches the agent. Rolling back is moving the label to the previous
one. Neither touches the repository.

### What is published, and what is not

Three prompts go to Langfuse:

| Prompt | What the model does with it |
|---|---|
| `rag-agent-system` | The rules it answers under |
| `rag-agent-search-tool` | Decides whether a question needs retrieval |
| `rag-agent-calculator-tool` | Decides whether a question needs arithmetic |

The line is what the text is for. A **description the model reads to decide**
is tuned the way a prompt is tuned, so it belongs where prompts are versioned.
The tool descriptions are exactly that: the model never sees a tool's body,
only its name and its description, and rewording one changes when it gets
called.

What stays in the code is the text a tool **returns**: `"Divisão por zero."`,
`"Nenhum trecho relevante encontrado na documentação."`. Those report what
happened during a run. They are facts about execution rather than instructions,
and nobody A/B tests them.

`_NO_RESULTS` sits closest to the line, since it is what prompts the agent to
say it found nothing. It stays in code because it states a fact; the
instruction to admit ignorance lives in the system prompt, where it can be
tuned.

Both tools are therefore built by a factory rather than the `@tool` decorator:
a decorator freezes the docstring at import, and a description fetched at call
time is the whole point.

### It never blocks an answer

Without Langfuse configured, the templates in `prompts.py` are used and
everything works. With Langfuse configured but unreachable, the same templates
are used and a warning is logged. A prompt store that can stop the agent from
answering is worse than no prompt store.

The SDK caches for `PROMPT_CACHE_SECONDS`, so a request does not pay a round
trip to fetch text that rarely changes.

### One placeholder syntax

Templates use `{{domain}}`, the form Langfuse compiles, on both paths. The
local text is therefore published verbatim, and the same string renders whether
it came from the platform or from the file.

### Recorded with the score

Every evaluation report carries `prompt_source` and `prompt_version` alongside
the model and the chunking. A run graded against version 3 cannot be compared
to one graded against version 4, and now the report says which was in force.

---

## Feedback

The evaluation dataset is written by whoever built the system, which means it
tests the questions that person thought of. Feedback from real use is the only
source of the ones they did not.

Every answer carries a `run_id`. Send it back with a verdict:

```bash
curl -X POST localhost:8080/feedback -H "Content-Type: application/json"   -d '{"run_id": "9b8c3a27...", "useful": false, "comment": "citou o artigo errado"}'
```

The verdict is recorded in Langfuse as a score on the trace that produced the
answer, which is where the platform already holds the prompt, the retrieved
passages and the cost of that same run. Send the `trace_id` alongside the
`run_id` to attach it.

A local copy is appended to `logs/feedback.jsonl` as well, so the loop still
closes with tracing switched off:

```json
{"recorded_at": "2026-08-31T15:31:04+00:00", "run_id": "9b8c3a27...",
 "useful": false, "comment": "citou o artigo errado", "sent_to_langfuse": true}
```

**What it is for.** The rejected answers are the candidates for new evaluation
cases. A question the agent got wrong in real use belongs in `dataset.json`,
and from then on it cannot regress unnoticed. That loop is what keeps the
suite from testing only what was imagined on the first day.

Nothing validates that a `run_id` belongs to a real answer. Rejecting unknown
ids would mean holding every answer in memory, and an occasional stray entry
costs less than that.

---

## Running with Docker

Three services: the agent, Postgres with pgvector, and Redis for sessions.
The index lives in its own container, with its own volume, and survives the
application entirely.

```bash
export OPENAI_API_KEY=sk-...        # Windows: $env:OPENAI_API_KEY='sk-...'

docker compose up -d                     # Postgres and Redis, then the API
docker compose run --rm api ingest       # build the index
curl localhost:8080/health
```

`docker compose up` brings up all three. The API waits for Postgres to accept
connections before starting, and has a healthcheck of its own hitting
`/health`. The extensions and the text search configuration are created by the
application on first use, so a fresh database needs no setup step.

The image serves the API by default and still runs the CLI on demand, because
the entrypoint is the `rag` command itself:

```bash
docker compose run --rm api ask "qual o prazo de suspensão de uma oferta?"
docker compose run --rm api eval
docker compose run --rm api ingest --reset
```

The index survives restarts:

```bash
docker compose restart postgres
docker compose run --rm api status   # still 590 chunks
```

`./data` is mounted read-only, so swapping the corpus needs no rebuild. To
tear everything down including the index:

```bash
docker compose down -v
```

**On image size:** the runtime image is ~422 MB, down from ~618 MB when the
store was Chroma. The saving is not an optimisation, it is a consequence:
`chromadb` pulled in `kubernetes` (83 MB), `onnxruntime` (66 MB) and Rust
bindings (57 MB), all of it machinery for running Chroma as a server, which
this container never did. A Postgres client is a driver.

---

## Observability

Every answer already reports its own cost locally. That tells you the total;
it does not tell you where the time and the tokens went. For that, the agent
can emit a full trace to [Langfuse](https://langfuse.com), with one row per
model call, tool call and retrieval, each carrying its own latency, tokens and
price.

```
rag.ask                                    3.78s   1634 tok   $0.00031
├─ ChatOpenAI                              1.71s    411 tok
│    └─ decided: search_documentation
├─ tool: search_documentation              0.54s
└─ ChatOpenAI                              1.52s   1223 tok
     └─ final answer
```

Turn it on by setting both keys. A free account at
[cloud.langfuse.com](https://cloud.langfuse.com) is enough:

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com     # or https://us.cloud.langfuse.com
```

Leave them out and nothing is sent, nothing is imported, and the agent behaves
identically. Observability must never break the thing it observes, so a rejected key or an
unreachable Langfuse logs a warning and disables itself instead of failing the
answer.

Each `rag chat` conversation gets a session id, so its turns group together in
the dashboard instead of appearing as unrelated runs. Traces carry the model,
the embedding model, the knowledge domain and `retrieval_k` as metadata, so a
trace from last month still explains which configuration produced it.

**Why it matters here:** the agent sometimes emits its tool calls in parallel,
deciding to `calculate` before it has read the retrieved passage. The answer
can still come out right while the number came from the model's memory rather
than from the document. In the terminal that is easy to miss. In a trace, the
two calls hanging off the same model call make it obvious.

---

## Evaluation

Unit tests prove the code does what it was written to do. They say nothing
about whether the agent answers correctly. That is a different question, and
the only one that tells you whether a change to the prompt, the chunking or
the model made things better or worse.

```bash
rag eval                     # the whole suite, ~2 minutes, ~US$ 0.02
rag eval --limit 5           # a quick sample
rag eval --min-score 0.90    # fail below 90% instead of below perfect
rag eval --max-cost 0.05     # fail if the run costs more than expected
rag eval --judge             # add a model that reads the sentence
rag eval --compare <report>  # diff against a previous run
rag eval --dataset my.json   # your own questions
```

```
$ rag eval --limit 5
  PASS lote-suplementar
  PASS lote-adicional
  PASS prazo-analise-sre
  PASS prazo-suficiencia
  PASS prazo-exigencias-primeiras
                           avaliação
┏━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ métrica   ┃ resultado ┃ o que mede                          ┃
┡━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ retrieval │      100% │ trouxe o documento certo            │
│ citação   │      100% │ citou a fonte certa                 │
│ fato      │      100% │ o número ou termo esperado apareceu │
│ recusa    │       n/a │ admitiu não saber, fora do corpus   │
│ fundamentação │  100% │ todo número saiu do que ele leu     │
│ geral     │      100% │ passou em tudo que se aplicava      │
└───────────┴───────────┴─────────────────────────────────────┘
gpt-4o-mini · k=8 · mediana 2.28s · 13728 tokens · ~US$ 0.0023
relatório salvo em evals/results/20260830-202941.json
```

`recusa` reads `n/a` here because none of the first five cases is an
out-of-corpus one: zero of zero applicable is not the same as failing.

The whole suite, all 29 cases, currently scores **97%**, with the single
failure described below.

Failures print with the answer, the documents retrieved and which metric broke,
and the command exits non-zero when the overall score falls below
`--min-score`, so it can gate a release.

Each run writes a timestamped report to `evals/results/`, and those are kept
in the repository. Every one records the model, the embedding model and
`retrieval_k` alongside the score, because a number without the configuration
behind it cannot be compared to the next run. The history shows the effect of a change: the reports here trace 82% to 86% to 93% to 97%, each step
a single setting.

### Groundedness

The other three metrics compare the answer against the dataset. This one
compares it against **what the agent actually read**.

Every number the answer states has to appear in a retrieved passage, in a tool
result, or in the question. A number found in none of those came from the
model's own memory, and not relying on that memory is the entire reason for
retrieval.

An answer can be correct, cite the right file, and still be ungrounded. That
combination holds only while the model's memory agrees with the document, and
it breaks silently on internal rules, a new version of a norm, anything the
training data does not already contain. Nothing else in the suite detects it.

Numbers are the claim worth checking in a regulation: they carry the deadlines,
the percentages and the limits, and they are what a model most confidently
invents. Matching normalises them, so "75 milhões" in an answer and "75000000"
in a calculator result are recognised as one number, and an answer with no
numbers is not graded rather than graded zero.

**Its limits, stated plainly:** it checks numbers, not prose. An invented
qualifier, a wrong name, a reversed condition all pass. And a false alarm on a
correct answer would leave the metric useless, so the matching is deliberately
lenient.

A first idea did not survive: flagging a tool call whose arguments hold a
number nobody had read yet, which would catch the agent choosing a multiplier
before the passage came back. Measured against the correct behaviour it fired
just as often, because a number legitimately changes form between the document
and the expression ("500 milhões" becomes `500000000`, "15%" becomes `0.15`).
A metric that cannot tell right from wrong was dropped rather than shipped.

### Comparing two runs

A directory of reports records what happened. It does not say what changed,
and reading two JSON files side by side to find out is how a history stops
being used.

```
$ rag eval --compare evals/results/20260830-212255.json

comparação com 20260830-212255.json
  retrieval_k          8 → 4
  overall              97% → 83%
  factual_accuracy     96% → 83%
  quebrado prazo-exigencias-primeiras
  1 regressão(ões)
```

Regressions are listed first, because a case that started failing is the one
worth reading. Above them sits the setting that moved, which is usually the
answer to why.

Every report records the settings behind it: the model, the embedding model,
the temperature, both chunking settings, `retrieval_k`, the knowledge domain,
and a hash of the rendered prompt. The prompt hash matters as much as the
rest: changing the wording changes the score, and without a fingerprint that
change leaves no trace.

Reports written before this carry only a few fields, and the comparison says
so rather than pretending nothing moved.

### Cost ceiling

```bash
rag eval --max-cost 0.05
```

Exits non-zero when the run costs more than expected. A prompt that grew
verbose, or a `retrieval_k` raised too far, shows up here as a number instead
of as a surprise on the invoice.

### Evaluation in CI

The suite runs from the Actions tab, and once a week on its own:

```
Actions → Evaluation → Run workflow → min_score, max_cost, limit
```

The weekly run exists because the corpus stops changing but the model does
not. A provider updating `gpt-4o-mini` underneath a frozen project moves the
score with no commit to blame, and a run every Monday is how that surfaces.
Each scheduled run commits its report, so the trend outlives the 30-day
artifact retention.

Each run reaches the real model, so it costs money and takes minutes. That is
the wrong trade for a per-push check, and the fast checks in `ci.yml` already
cover every push. The report is uploaded as an artifact, including when the run
falls below the threshold, since that is the one whose detail someone needs to
read.

It needs `OPENAI_API_KEY` in **Settings → Secrets and variables → Actions**.
Without it the job skips with a message instead of failing, because a pull
request from a fork never receives secrets.

### Relation to existing tools

The metric names used here are local. The concepts are not: each one has an
established name in the RAG evaluation literature.

| This project | Standard name | Where it is found |
|---|---|---|
| `retrieval` | context recall | RAGAS |
| `correctness` | answer correctness | RAGAS, DeepEval |
| `groundedness` | faithfulness, computed | RAGAS, TruLens |
| `faithfulness` | LLM-as-a-judge faithfulness | RAGAS, LangSmith, DeepEval |
| `citation` | attribution | LangSmith |
| `refusal` | hallucination rate on unanswerable questions | RAGAS |

RAGAS, LangSmith Evaluation, DeepEval and Langfuse Datasets all cover this
ground, and none of them is used here. They share one default: a language
model grades the answers. That costs money on every run and it drifts:
the same answer can score differently twice, and a suite whose numbers move on
their own cannot tell a regression from noise.

The trade taken instead: deterministic scoring against a smaller dataset
verified by hand. Twenty-nine cases whose answers were read out of the source
documents, graded by string and set operations. The cost is coverage, since
these metrics check numbers and file names rather than meaning. The gain is
that the same run always produces the same number, and it costs nothing to
grade.

A judge model is the right call for grading prose, where the wording
legitimately varies and a string match cannot tell a faithful sentence from a
distorted one. That is exactly what `--judge` adds, kept separate and opt-in
so the reproducible scores stay reproducible.

### Hybrid search

Two retrievers run and their rankings are fused.

An embedding compares meaning, which is what lets a question find a passage
that shares none of its words. It also spreads a long article's signal across
everything the article discusses, so one sentence stating a deadline ranks
below whatever the article is mostly about.

Postgres full text search compares words. It cannot follow a paraphrase, and
it does not need to
when the question names the terms the text uses.

Measured on this corpus, on the question the suite failed for weeks: the
passage stating the suspension deadline sits at **rank 31 by embedding** and at
**rank 5 by keyword**.

The two lists are merged by reciprocal rank fusion. Each document scores the
sum of `1 / (60 + rank)` over the lists it appears in, so a passage both
retrievers rank well beats one a single retriever loves. Fusing on rank rather
than on score is what makes it work at all: a cosine distance and a text search rank
are not on the same scale and cannot be added.

Each retriever is asked for five times the passages wanted, and the fused list
is cut back. Fusing two short lists only rewards what both retrievers already
agreed on, which is what either would have found alone; the passages worth
adding sit deeper in one list. Measured here, the missing deadline reaches the
top eight at a multiplier of five and not at three.

`SEARCH_STRATEGY=vector` turns the keyword half off. The keyword index is built
once from what is stored and dropped whenever the store changes, since it is a
copy.

**What it fixed:** the last failing case, and with it `correctness` and
`faithfulness`. Every metric now reads 100% on 29 questions.

**What that number is worth:** the five deterministic metrics are reproducible,
so 100% there means 100% again tomorrow. `faithfulness` is graded by a model
and drifts; one run at 100% is not a guarantee of the next.

### Probes, limits and workers

| Endpoint | Answers | Checks |
|---|---|---|
| `GET /health` | liveness | nothing else |
| `GET /ready` | readiness | database reachable, index populated |

**They were one endpoint once, and it checked the database.** That is
readiness wearing a liveness name: an orchestrator restarts a process whose
liveness probe fails, so a database blinking would have restarted every
replica at once, and that is how one database problem becomes an outage. A
failed readiness probe takes the instance out of rotation and leaves it
running, which is the right answer to a dependency that is briefly away.

The container healthcheck points at `/ready`, because Compose's
`service_healthy` means "ready for traffic".

**Rate limiting** is a moving window per caller: `60/minute` by default, empty
to disable. A caller is its API key when there is one and its address when
there is not, and the key is hashed before it becomes a storage key. Every
answer carries `X-RateLimit-Remaining`, so a client slows down before being
refused rather than after. The probes are never limited: a balancer polling
readiness every two seconds would exhaust a per-minute budget on its own.

> **Not slowapi.** It is the usual answer for FastAPI and it does not work
> here. Both of its middlewares find the route by walking `app.routes` for
> something with an `.endpoint`, and current FastAPI wraps everything from
> `include_router` in an `_IncludedRouter` that has none. Every request looks
> like a route it cannot identify, which it treats as exempt. The failure is
> silent: the limiter reports itself enabled and the ceiling never fires. What
> is used instead is `limits`, the library slowapi is built on.

**Workers**: `rag serve --workers 4`, or `API_WORKERS`. One process serialises
requests, so a question that takes eight seconds blocks every other question
for those eight seconds. `--reload` needs a single process and wins over
`--workers`, which the command says rather than silently ignoring one.

### Schema migrations

Alembic owns the extensions and the `portuguese_unaccent` text search
configuration. The tables belong to langchain-postgres, which creates them on
first write, and the two search indexes are built after that because they
cannot exist before the table does.

```bash
alembic upgrade head      # prepare a database
alembic revision -m "..."  # start a change
alembic downgrade -1       # undo the last one
```

The URL is not in `alembic.ini`. `migrations/env.py` reads `DATABASE_URL`
through the same settings object the application uses, so there is one place
that knows where the database is and no credential in a tracked file.

**The application does not apply migrations.** It used to, and that is an
anti-pattern past one replica: several processes starting together race to
create the same objects, and a long migration blocks every boot rather than
one deployment step. What the application does now is check, and fail naming
the command:

```
O banco em postgresql+psycopg://rag:***@localhost:5432/rag não tem as
migrações aplicadas. Rode: alembic upgrade head
```

In Compose a one-shot `migrate` service runs first and the API waits on
`service_completed_successfully`.

### Guardrails

Three layers on the way in, one on the way out. They run from
`agent/service.py`, so the CLI and the API are covered by construction and a
new interface cannot forget.

| Layer | Checks | On failure |
|---|---|---|
| Arithmetic | Empty, and length against `MAX_QUESTION_CHARS` | Refuses |
| Scanning | Secrets, e-mail, credit card, and **CPF, CNPJ, API keys** | Refuses |
| Injection | Whether the question is an instruction | Refuses |
| Output | Citation present, token ceiling | **Records a finding** |

**A question is refused before it costs anything. An answer has already been
paid for by the time it can be judged**, so what happens to it is a finding
attached to the result, never an exception. Citation in particular is a
finding and not a refusal: a correct refusal cites nothing, and this corpus
has four questions it cannot answer on purpose.

#### LLM Guard, configured rather than used as shipped

LLM Guard is the standard and it is built for English. Its own
`ALL_SUPPORTED_LANGUAGES` is `["en", "zh"]` and its default entity list is
`US_SSN` and `US_BANK_NUMBER`. Measured here, before any configuration:

| Question | Verdict |
|---|---|
| "qual o prazo máximo de suspensão?" | **refused**, confidence 1.00 |
| "what is the maximum suspension period?" | passed |
| "o que diz o Art. 70 da Resolução 160?" | **refused**, read 160 as an account number |
| a CPF | **passed** |

It refused every real question and missed the one identifier that matters in
Brazil. What fixed it: dropping its English-only injection scanner, narrowing
`entity_types` to the language-neutral patterns, and adding CPF, CNPJ and API
keys by regex.

#### The injection classifier was chosen by measurement

Eight cases, four of them attacks, half in Portuguese:

| Model | Correct | False positives |
|---|---|---|
| **`katanemolabs/Arch-Guard`** | **7/8** | **0** |
| `testsavantai/prompt-injection-defender-large-v0` | 6/8 | 0 |
| `jackhhao/jailbreak-classifier` | 5/8 | 0 |
| `protectai/deberta-v3-base-prompt-injection-v2` | 5/8 | **3** |

The last row is LLM Guard's default. Meta's Prompt Guard 2 is the model the
market reaches for first and is multilingual by design; it is also a gated
repository, so it needs a licence and a token. `INJECTION_MODEL` switches to
it in one setting.

#### Indirect injection is the risk that belongs to RAG

A retrieved passage is pasted into the context and the model reads it the way
it reads the system prompt. A retriever works in embedding space and has no
notion of "this is data" rather than "this is an instruction", so a document
carrying a hidden instruction attacks **every question that retrieves it**.

The corpus is therefore scanned **at ingestion**, once per chunk, never per
question: the documents change only when someone indexes them, so the answer
cannot change between two questions. Measured on five chunks with one
poisoned: one flagged, four genuine articles clean.

A flagged chunk warns rather than refuses. This corpus is regulation, and
regulation tells the reader what to do, so a classifier trained on jailbreaks
will sometimes read a genuine article as an instruction. Refusing to index
would silently drop the law.

#### What is not covered

- **Permission-aware retrieval.** Anyone who can ask can retrieve any chunk.
- **Output PII.** Only the question is scanned.
- **Rate limiting.** No per-caller cost ceiling yet.

### Reranking

Off by default. This section is as much about why as about how.

**What a reranker is.** A second pass that reorders the passages the search
already retrieved. It finds nothing of its own.

```
retrieval  ──▶  24 candidates  ──▶  reranker  ──▶  8 passages  ──▶  agent
   wide, cheap                       narrow, expensive
```

**Why it is more accurate.** Every retriever above compares two things through
something precomputed. A passage is embedded at ingestion, months before the
question exists, so its vector compresses the text without knowing what will
be asked of it. A cross-encoder reads the question and the passage together,
in one forward pass, and answers directly: does this passage answer that one.

That is also why it is expensive. Nothing can be precomputed, so the cost is
one model pass per candidate, on every question.

| | Embedding | Cross-encoder |
|---|---|---|
| Reads the pair together | No | Yes |
| Computed when | At ingestion | At query time |
| Cost | A lookup | A forward pass per candidate |
| Scales to | Millions of passages | Dozens |

**Why it is off here.** A reranker fixes precision. It cannot repair a pool
the answer is not in. The failure this suite had for weeks was recall:
measured on this corpus, the passage stating the suspension deadline sat at
rank 31 of 590 by embedding. With `RETRIEVAL_K=8` a reranker would have been
handed eight passages that did not contain the answer, and would have returned
eight passages that still did not. Hybrid search is what fixed it.

Turning it on would add latency and a two gigabyte dependency for a measured
gain of nothing, on a corpus where every metric already reads 100%.

**What it looks like when it works.** Measured with the default model on five
real passages from this corpus, with the answer deliberately placed last, as
it would arrive from a wide pool:

| After reranking | Was | Score | Passage |
|---|---|---|---|
| 1 | 5 | `+0.9723` | `§ 2º O prazo de suspensão da oferta não pode ser superior a 30 dias.` |
| 2 | 2 | `+0.2308` | `Art. 70. A SRE pode suspender ou cancelar, a qualquer tempo…` |
| 3 | 1 | `+0.0050` | `Art. 12. O lote suplementar não pode ultrapassar 15%…` |
| 4 | 3 | `+0.0004` | `Art. 25. O prospecto deverá ser elaborado…` |
| 5 | 4 | `+0.0001` | `Art. 3. Consideram-se atos de distribuição pública…` |

The gap between the first two is the useful part. The passage that merely
mentions suspension scores 0.23; the one that states the deadline scores 0.97.
An embedding cannot separate those, because both are about suspending an
offer.

**When to turn it on.** When the pool is wide enough that the answer is in it
but not near the top. That is the normal condition at scale, and it is why the
two-stage shape exists at all: with millions of passages you must retrieve
a hundred or more to be confident of recall, and a hundred passages do not fit
in a prompt. The reranker is the funnel between those two facts.

```bash
RERANK_STRATEGY=cross_encoder rag ask "qual o prazo de suspensão?"
```

The package is already installed: guardrails need torch, so the reranker costs
almost nothing on top of it. The weights are a 2.2 GB download on first use.

The pool widens on its own when it is enabled: `RERANK_CANDIDATES` replaces
`RETRIEVAL_K` as the retrieval width, because a reranker handed exactly what
it returns has nothing to choose between.

**On the dependency.** A local cross-encoder means torch. That used to be
the argument for keeping it optional, and it stopped being one when the
guardrails made torch a hard dependency anyway. At scale the answer is neither
in-process nor optional, it is a reranking service of its own, so the model is
loaded once behind an endpoint instead of once per API replica. The interface
here is one method, so that is a class, not a rewrite.

**On sending text to an API.** Cohere Rerank is the commercial standard and is
very good. It also means the corpus leaves the network. For a regulated
institution that is usually the end of the discussion, which is why the local
model is the default choice here.

### The six metrics

| Metric | Needs the expected answer? | What it checks |
|---|---|---|
| `retrieval` | yes | The right document came back from the search |
| `citation` | yes | The answer names the right source |
| `correctness` | yes | The expected number or term is present |
| `refusal` | yes | Outside the corpus, it admitted not knowing |
| `groundedness` | no | Every number stated appears in what it read |
| `faithfulness` | no | The sentence matches the passage, graded by a model |

The split in the middle column is the one that matters, and it is why the
metrics live in code rather than as evaluators on the platform.

The first four compare an answer against a **known right answer**. They only
exist where there is a dataset. A real user's question has no expected output,
so nothing can grade it that way.

The last two compare the answer against **what the agent retrieved**. They need
no expected answer, which is why they would also work on production traffic.
The literature calls these reference-free, and they are what RAGAS built its
reputation on.

`faithfulness` is not a layer on top of the others. It is the sixth metric,
and the only one computed by a model instead of by string comparison. It exists
because the other five pass an answer that states the right figure while
inverting the condition around it: the regulation says a fact **may** be
withheld, the answer says it **must** be, and no number moved.

### On the platform

The local suite writes one report per run into `evals/results/`. That works
until the directory grows past what anyone opens, and the only comparison it
offers is a command reading two files.

Pushing the dataset to Langfuse turns each run into a tracked experiment:

```bash
rag dataset push          # send the questions to Langfuse
rag eval                  # run them there
```

Every case gets its own trace, the five metrics hang off it as scores, and two
runs sit side by side in a UI built for that comparison. The run carries the
configuration as metadata, so a score is never separated from the settings that
produced it.

The run carries the configuration as metadata, and the terminal prints the
same table it prints locally.

The dataset file stays in git. A dataset versioned alongside the code is what
makes a score reproducible, and it is the standard: the questions change with
the system, and a pull request that adds a case should show that case in the
diff. What moves to the platform are the results.

The case id becomes the item id, so `dataset push` updates items in place
rather than duplicating them, the same way ingestion is idempotent.

The metrics are the same functions the local suite uses, wrapped as Langfuse
evaluators. Reusing them is what keeps the two paths from disagreeing, and
they stay deterministic and free either way.

A metric that does not apply records nothing rather than a zero. Zero would
read as a failure, and the schema rejects null: an out-of-corpus question has
no retrieval to grade, and saying so is different from failing it.

### Human review

With the dataset on the platform, the annotation queue works with no code at
all. Send traces to a queue in the Langfuse UI, review the answers by hand, and
the labels come back as scores next to the automatic ones. It is the one thing
here no deterministic metric can do: judge whether an answer reads well and
means what the document means.

### The dataset

`evals/dataset.json` holds 29 questions: 25 answerable and **4 deliberately
outside the corpus**. The out-of-corpus cases are the important ones. They
measure whether the agent admits ignorance instead of inventing, which nothing
else in the project can catch.

Every fact was extracted from the indexed PDFs, not written from memory.

### Every metric is deterministic

No second model grades the answers. A language model used as a judge drifts
between runs, and a suite you cannot trust has no value. The four metrics
are string and set operations: same answer, same score, no extra cost.

The trade-off is honest: `retrieval` checks that the right *document* came
back, not the right *passage*. In a 143-page regulation full of near-identical
deadlines, that is a coarse instrument, and the failures below exposed exactly
that.

### What it found

Running it for the first time paid for itself immediately:

| Finding | Fix | Result |
|---|---|---|
| Right document, wrong deadline: 5 cases where the answer cited the correct file with the wrong number | `RETRIEVAL_K` 4 → 8 | 82% → 86% |
| The agent never stopped searching for an answer that was not there, until the context window overflowed and killed the whole run | A rule capping retries, plus `recursion_limit` on the graph | 86% → 93% |
| One failing case aborted the entire suite | Per-case error isolation in the runner | The other 27 results survive |
| A question so ambiguous the agent was graded wrong for a correct answer, since the article carries five different deadlines for "exigências" | Split into two specific questions | The dataset got honest |
| Rules separated from the exceptions that qualify them, because chunking cut every 1000 characters | `CHUNK_STRATEGY=articles` | 93% → 97% |
| Nothing checked whether an answer's numbers came from the documents or from the model's memory | Groundedness | 100%, so far a regression guard rather than a finding |

The first is the dangerous one: a wrong number with a correct citation looks
more trustworthy than a wrong number alone.

A failing case has three possible causes, and only reading the answer tells
them apart: the agent wrote badly, retrieval fetched the wrong passage, or the
question itself was ambiguous. Mistaking the third for the first means
"fixing" an agent that was right.

---

## Development

With the environment active:

```bash
pytest                          # full suite
pytest -v                       # one line per test
pytest -m "not integration"     # fast tests only, no network, no API cost
pytest --cov=rag_agent          # with coverage
pytest -k calculator            # filter by name

ruff check . && ruff format .   # lint and format
mypy                            # type check
```

Every push runs the same four checks on Ubuntu and Windows through GitHub
Actions (`.github/workflows/ci.yml`). Integration tests are excluded there: a
public repository has no business holding an API key, and every push would
spend tokens.

Unit tests cover the pure logic (chunking, the calculator, settings, the
service loop with a fake model) and need no API key. Tests marked
`integration` hit the real embedding API and are skipped without one.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `rag` not recognized / command not found | The virtual environment is not active. Run `.\.venv\Scripts\Activate.ps1`, or call `.\.venv\Scripts\rag.exe` directly. |
| `running scripts is disabled on this system` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, once. |
| `pytest` not recognized | Same cause. Activate the environment first. |
| `O índice está vazio` | Run `rag ingest` |
| `Pasta de dados não encontrada` | Check `DATA_DIR` with `rag status` |
| OpenAI authentication error | Check `OPENAI_API_KEY` in `.env` |
| Nonsense answers after changing models | Run `rag ingest --reset` |
| Answers missing detail | Raise `RETRIEVAL_K` or `CHUNK_SIZE` |
| Broken accents on Windows | `set PYTHONIOENCODING=utf-8` |
| `pip install -e .` fails on a torch header | Enable long path support on Windows: `Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Value 1` |
| Every question refused as injection | Check `INJECTION_MODEL`. The LLM Guard default refuses Portuguese |
| `RerankerUnavailableError` | Reinstall dependencies, or set `RERANK_STRATEGY=none` |
| Postgres unreachable | `docker compose up -d postgres`, or check `DATABASE_URL` |

---

## License

MIT.
