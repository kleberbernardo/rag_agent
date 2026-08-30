# RAG Agent

[![CI](https://github.com/kleberbernardo/rag_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/kleberbernardo/rag_agent/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

A command-line AI agent that answers questions about your own documents.

Point it at a folder of files, run the ingestion, and ask questions in plain
language. The agent retrieves the relevant passages before answering and cites
the file it took each answer from. When the answer is not in your documents, it
says so instead of inventing one.

- **Grounded** — answers come from retrieved passages, never from model memory.
- **Cited** — every answer names its source file.
- **Agentic** — the model decides when to search, can search again with
  different terms, and can reach for other tools.
- **Local index** — the vector store is an embedded database on disk. No server
  to run, or point it at a standalone Chroma with one variable.
- **Domain-agnostic** — the subject lives in configuration, not in code. Swap
  the folder, change one variable, re-ingest.

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
> Activation lasts for that terminal window only — open a new one and you have
> to activate again. This is the single most common reason `rag` "does not
> work".

Every session starts like this:

```powershell
.\.venv\Scripts\Activate.ps1     # Windows — source .venv/bin/activate elsewhere
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
consolidated resolutions from the CVM, the Brazilian securities regulator —
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
idempotent — running it twice updates the same records instead of duplicating
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
```

The agent did not do the arithmetic itself — it delegated the multiplication
to the calculator, and cited the page it took the limit from.

### 4. Or hold a conversation

```bash
rag chat
```

Keeps context between turns, so follow-up questions work without repeating the
subject. Exit with `sair`, `exit` or `Ctrl+C`.

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
at boot — an invalid setting stops the program immediately with a clear message
rather than failing mid-query.

| Variable | Default | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | — | **Required.** |
| `CHAT_MODEL` | `gpt-4o-mini` | Model that reasons and picks tools. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Model that turns text into vectors. |
| `TEMPERATURE` | `0.0` | `0` is deterministic — what you want for grounded answers. |
| `CHUNK_SIZE` | `1000` | Max characters per chunk. |
| `CHUNK_OVERLAP` | `200` | Characters repeated between neighbouring chunks. |
| `RETRIEVAL_K` | `4` | Passages retrieved per question. |
| `KNOWLEDGE_DOMAIN` | generic | What the corpus is about. Injected into the system prompt and the search tool description. |
| `DATA_DIR` | `data/` | Where your documents live. |
| `VECTOR_STORE_MODE` | `embedded` | `embedded` for a local file, `server` for a standalone Chroma. |
| `VECTOR_STORE_DIR` | `.chroma/` | Where the index is written in embedded mode. |
| `CHROMA_HOST` / `CHROMA_PORT` | `localhost` / `8000` | The Chroma server address, used in server mode. |
| `COLLECTION_NAME` | `rag_agent_docs` | Collection name inside the store. |

---

## How it works

The system has two phases that never run at the same time.

### Phase 1 — Ingestion (offline)

```
data/*  ──▶  load  ──▶  split  ──▶  embed  ──▶  .chroma/
          (loader)   (splitter)  (providers)  (vector_store)
```

**Load** — each file becomes a `Document` carrying its filename as metadata.
That metadata is what lets the final answer cite a source. PDFs become one
document per page, so a citation can point at a page number.

**Split** — documents are cut into chunks of `CHUNK_SIZE` characters, breaking
at paragraph boundaries first, then lines, then sentences, then words. Chunks
overlap by `CHUNK_OVERLAP` characters so an idea that falls across a boundary
survives whole in at least one of them.

**Embed** — each chunk is sent to the embedding model and comes back as a
vector: a list of numbers positioning that text in semantic space. Chunks that
mean similar things land near each other.

**Store** — vectors are written to Chroma. Each chunk gets an id derived from
a hash of its source and content, which is what makes re-ingestion overwrite
rather than duplicate.

The store runs in one of two modes, chosen by `VECTOR_STORE_MODE`:

| Mode | What it is | When |
|---|---|---|
| `embedded` | A local file. Nothing to run. | Default — clone and try it |
| `server` | A standalone Chroma over HTTP | Storage that restarts and scales apart from the app |

Both expose the same interface, so switching is a configuration change. In
server mode an unreachable Chroma fails with an actionable message instead of
a driver stack trace.

### Phase 2 — Query (online)

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
in the text — matching happens on meaning, not on words.

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
body — only the name, the signature and the docstring. **The docstring is the
contract**: it is how the model decides when the tool applies.

- `search_documentation` — semantic search over the indexed chunks.
- `calculate` — a safe arithmetic evaluator. Language models are unreliable at
  arithmetic, so anything numeric is delegated here. Expressions are parsed
  into a syntax tree and checked against an allow-list, so a model-authored
  string can never become arbitrary code execution.

To add one: write the function with the `@tool` decorator in its own module
under `tools/`, then register it in `TOOLS`.

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
├── types.py           AnswerResult, SearchHit, ToolCall
├── providers.py       LLM and embedding clients — the only place OpenAI appears
├── prompts.py         the agent's permanent instructions
├── logging_setup.py   console and file logging
├── cli.py             presentation only, no domain logic
├── indexing/          loader · splitter · vector_store
├── tools/             one module per tool, registered in TOOLS
└── agent/             service (build + orchestration) · trace
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

Interfaces stay thin because orchestration lives in `agent/service.py`. Adding
an HTTP API or a bot means wrapping that service, not rewriting it.

---

## Running with Docker

Two services: the agent and a standalone Chroma. This is what
`VECTOR_STORE_MODE=server` exists for — the index lives in its own container,
with its own volume, and survives the application entirely.

```bash
export OPENAI_API_KEY=sk-...        # Windows: $env:OPENAI_API_KEY='sk-...'

docker compose up -d chroma         # start the vector store
docker compose run --rm rag ingest  # build the index
docker compose run --rm rag ask "quem deve divulgar informação relevante?"
```

`docker compose up` starts only Chroma. The agent is a one-shot command, not a
daemon, so it runs through `docker compose run` and exits — which is why it
sits behind a `cli` profile instead of starting on its own.

The index survives restarts:

```bash
docker compose restart chroma
docker compose run --rm rag status   # still 687 chunks
```

`./data` is mounted read-only, so swapping the corpus needs no rebuild. To
tear everything down including the index:

```bash
docker compose down -v
```

**On image size:** the runtime image is ~618 MB. Most of that is `chromadb`
pulling in `kubernetes` (83 MB), `onnxruntime` (66 MB) and Rust bindings
(57 MB) — machinery for running Chroma as a server, which this container never
does. Swapping to the thin `chromadb-client` would cut roughly 200 MB, at the
cost of an image that can no longer run in embedded mode. Not worth the hidden
constraint for the saving.

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

Unit tests cover the pure logic — chunking, the calculator, settings, the
service loop with a fake model — and need no API key. Tests marked
`integration` hit the real embedding API and are skipped without one.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `rag` not recognized / command not found | The virtual environment is not active. Run `.\.venv\Scripts\Activate.ps1`, or call `.\.venv\Scripts\rag.exe` directly. |
| `running scripts is disabled on this system` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, once. |
| `pytest` not recognized | Same cause — activate the environment first. |
| `O índice está vazio` | Run `rag ingest` |
| `Pasta de dados não encontrada` | Check `DATA_DIR` with `rag status` |
| OpenAI authentication error | Check `OPENAI_API_KEY` in `.env` |
| Nonsense answers after changing models | Delete `.chroma/` and re-ingest |
| Answers missing detail | Raise `RETRIEVAL_K` or `CHUNK_SIZE` |
| Broken accents on Windows | `set PYTHONIOENCODING=utf-8` |

---

## License

MIT.
