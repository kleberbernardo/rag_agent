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
- **Local index**: the vector store is an embedded database on disk. No server
  to run, or point it at a standalone Chroma with one variable.
- **Measured**: every answer reports its latency, token usage and estimated
  cost, with optional full tracing to Langfuse.
- **Domain-agnostic**: the subject lives in configuration, not in code. Swap
  the folder, change one variable, re-ingest.
- **Evaluated**: 29 graded questions, including ones the corpus cannot answer.
  Currently 97%.
- **Two interfaces**: a CLI and an HTTP API over the same service layer, both
  in one container.

---

## Architecture

Two phases that never run at the same time, and two interfaces over one
service layer.

```
INGESTION  ·  offline, `rag ingest`

   data/*.pdf ──► loader ──► splitter ──► embeddings ──► Chroma
                  pdf, md    per article    OpenAI       embedded file
                  txt, rst   Art. 1, 2…                  or server


QUERY  ·  online

   CLI  rag ask ───┐
                   ├──► service ──► agent ──┬──► search_documentation ──► Chroma
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
| Retrieval | `indexing/` | Load, split, embed, search. |
| Providers | `providers.py` | The only place OpenAI appears. |
| Behaviour | `prompts.py` | The rules, rendered per domain. |
| Measurement | `evaluation/` | Grade the agent against known answers. |

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
`KNOWLEDGE_DOMAIN` in `.env`, delete `.chroma/` and re-ingest.

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
| `RETRIEVAL_K` | `8` | Passages retrieved per question. |
| `KNOWLEDGE_DOMAIN` | generic | What the corpus is about. Injected into the system prompt and the search tool description. |
| `DATA_DIR` | `data/` | Where your documents live. |
| `LOG_DIR` | `logs/` | Where the log file is written. |
| `VECTOR_STORE_MODE` | `embedded` | `embedded` for a local file, `server` for a standalone Chroma. |
| `VECTOR_STORE_DIR` | `.chroma/` | Where the index is written in embedded mode. |
| `CHROMA_HOST` / `CHROMA_PORT` | `localhost` / `8000` | The Chroma server address, used in server mode. |
| `COLLECTION_NAME` | `rag_agent_docs` | Collection name inside the store. |
| `LANGFUSE_PUBLIC_KEY` | none | Optional. Enables tracing when set together with the secret key. |
| `LANGFUSE_SECRET_KEY` | none | Optional. See [Observability](#observability). |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse region, e.g. `https://us.cloud.langfuse.com`. |

---

## How it works

The system has two phases that never run at the same time.

### Phase 1: ingestion (offline)

```
data/*  ──▶  load  ──▶  split  ──▶  embed  ──▶  .chroma/
          (loader)   (splitter)  (providers)  (vector_store)
```

**Load**. Each file becomes a `Document` carrying its filename as metadata.
That metadata is what lets the final answer cite a source. PDFs become one
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

**Store**. Vectors are written to Chroma. Each chunk gets an id derived from
a hash of its source and content, so re-ingestion overwrites instead of
duplicating.

The store runs in one of two modes, chosen by `VECTOR_STORE_MODE`:

| Mode | What it is | When |
|---|---|---|
| `embedded` | A local file. Nothing to run. | Default: clone and try it |
| `server` | A standalone Chroma over HTTP | Storage that restarts and scales apart from the app |

Both expose the same interface, so switching is a configuration change. In
server mode an unreachable Chroma fails with an actionable message instead of
a driver stack trace.

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

> Change `EMBEDDING_MODEL` and you must delete `.chroma/` and re-ingest.
> Vectors from different models are not comparable.

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
├── prompts.py         the agent's permanent instructions, rendered per domain
├── pricing.py         token prices, used to estimate what a run cost
├── observability.py   optional Langfuse tracing, inert without keys
├── logging_setup.py   console and file logging
├── cli.py             presentation only, no domain logic
├── indexing/          loader · splitter · vector_store
├── tools/             one module per tool, registered in build_tools()
├── agent/             service (build + orchestration) · trace
├── api/               FastAPI wrapper: routes · schemas · sessions
└── evaluation/        dataset · metrics · runner
```

Only three directories, and each earns it: `indexing/` grows with every new
file format, `tools/` with every new tool, `agent/` holds the orchestration.
Everything else is a single module.

| To change... | Edit |
|---|---|
| The knowledge base | `data/`, then `rag ingest` |
| How the agent behaves | `prompts.py` |
| Add a tool | `tools/` |
| Chunking or retrieval | `.env` |
| The model provider | `providers.py` |
| Token prices | `pricing.py` |
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

**Sessions live in the process that served them.** A second replica would not
see them, and a restart forgets everything. The store caps at 100 conversations
and evicts the oldest, because each one holds its whole message history and an
unbounded dictionary is a memory leak with a friendly name. Making sessions
survive means Redis or a database, which is a decision to take when there is a
second replica, not before.

### Failure modes

| Situation | Response |
|---|---|
| Empty index | `503` naming the ingestion step |
| Chroma unreachable | `503` naming the address it tried |
| Malformed body | `422` from the schema |
| Unknown session on delete | `404` |

An unknown `session_id` on `POST /chat` opens a new conversation rather than
failing: a client holding an id from before a restart should keep working.

---

## Running with Docker

Two services: the agent and a standalone Chroma. This is what
`VECTOR_STORE_MODE=server` exists for. The index lives in its own container,
with its own volume, and survives the application entirely.

```bash
export OPENAI_API_KEY=sk-...        # Windows: $env:OPENAI_API_KEY='sk-...'

docker compose up -d                     # Chroma, then the API
docker compose run --rm api ingest       # build the index
curl localhost:8080/health
```

`docker compose up` brings up both services. The API waits for Chroma to report
healthy before starting, and has a healthcheck of its own hitting `/health`.

The image serves the API by default and still runs the CLI on demand, because
the entrypoint is the `rag` command itself:

```bash
docker compose run --rm api ask "qual o prazo de suspensão de uma oferta?"
docker compose run --rm api eval
docker compose run --rm api ingest --reset
```

The index survives restarts:

```bash
docker compose restart chroma
docker compose run --rm api status   # still 590 chunks
```

`./data` is mounted read-only, so swapping the corpus needs no rebuild. To
tear everything down including the index:

```bash
docker compose down -v
```

**On image size:** the runtime image is ~618 MB. Most of that is `chromadb`
pulling in `kubernetes` (83 MB), `onnxruntime` (66 MB) and Rust bindings
(57 MB), all of it machinery for running Chroma as a server, which this
container never does. Swapping to the thin `chromadb-client` would cut roughly 200 MB, at the
cost of an image that can no longer run in embedded mode. Not worth the hidden
constraint for the saving.

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
behind it cannot be compared to the next run. The history is what shows the
effect of a change: the reports here trace 82% to 86% to 93% to 97%, each step
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
correct answer would make the metric worse than useless, so the matching is
deliberately lenient.

A first idea did not survive: flagging a tool call whose arguments hold a
number nobody had read yet, which would catch the agent choosing a multiplier
before the passage came back. Measured against the correct behaviour it fired
just as often, because a number legitimately changes form between the document
and the expression ("500 milhões" becomes `500000000`, "15%" becomes `0.15`).
A metric that cannot tell right from wrong was dropped rather than shipped.

### Evaluation in CI

The suite runs from the Actions tab, not on every push:

```
Actions → Evaluation → Run workflow → min_score
```

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
| retrieval | context recall | RAGAS |
| fato | answer correctness | RAGAS, DeepEval |
| fundamentação | faithfulness, groundedness | RAGAS, TruLens |
| citação | attribution | LangSmith |
| recusa | hallucination rate on unanswerable questions | RAGAS |

RAGAS, LangSmith Evaluation, DeepEval and Langfuse Datasets all cover this
ground, and none of them is used here. They share one default: a language
model grades the answers. That costs money on every run and, worse, drifts —
the same answer can score differently twice, and a suite whose numbers move on
their own cannot tell a regression from noise.

The trade taken instead: deterministic scoring against a smaller dataset
verified by hand. Twenty-nine cases whose answers were read out of the source
documents, graded by string and set operations. The cost is coverage, since
these metrics check numbers and file names rather than meaning. The gain is
that the same run always produces the same number, and it costs nothing to
grade.

A judge model would be the right call for a larger dataset, or for grading
prose where the wording legitimately varies. At this size it would buy noise.

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
| Nonsense answers after changing models | Delete `.chroma/` and re-ingest |
| Answers missing detail | Raise `RETRIEVAL_K` or `CHUNK_SIZE` |
| Broken accents on Windows | `set PYTHONIOENCODING=utf-8` |

---

## License

MIT.
