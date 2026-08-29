# RAG Agent

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
  to run.

---

## Installation

Requires Python 3.12+ and an OpenAI API key.

```bash
python -m venv .venv

# Windows
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

pip install -e ".[dev]"

cp .env.example .env        # Windows: copy .env.example .env
```

Then put your API key in `.env`:

```
OPENAI_API_KEY=sk-...
```

Installing with `-e` means code changes take effect immediately, and it
registers the `rag` command. Without installing, use `python main.py` instead.

---

## Usage

### 1. Add your documents

Drop files into `data/`. Supported: `.md`, `.txt`, `.markdown`, `.rst` and
`.pdf`. Subfolders are scanned recursively; anything else is skipped.

The repository ships with sample documentation so you can try it immediately.

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
rag ask "what are the technical limits?"
rag ask "what does a full year cost?" --trace
```

`--trace` prints the agent's reasoning: which tools it chose, with which
arguments, and what each returned.

```
$ rag ask "what does the mid-tier plan cost per year?" --trace

╭─ raciocínio ───────────────────────────────────────────╮
│ [AGENTE decide] chamar search_documentation(...)       │
│ [FERRAMENTA] -> R$ 890 per month...                    │
│ [AGENTE decide] chamar calculate({'expr': '890 * 12'}) │
│ [FERRAMENTA] -> 10680                                  │
╰────────────────────────────────────────────────────────╯
╭─ resposta ─────────────────────────────────────────────╮
│ R$ 890 per month, so R$ 10,680 per year.               │
│ (fonte: produto.md)                                    │
╰────────────────────────────────────────────────────────╯
```

Note that the agent did not do the arithmetic itself — it looked up the price
and delegated the multiplication.

### 4. Or hold a conversation

```bash
rag chat
```

Keeps context between turns, so follow-up questions work. Exit with `sair`,
`exit` or `Ctrl+C`.

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
| `DATA_DIR` | `data/` | Where your documents live. |
| `VECTOR_STORE_DIR` | `.chroma/` | Where the index is written. |
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

**Store** — vectors are written to an embedded Chroma database on disk. Each
chunk gets an id derived from a hash of its source and content, which is what
makes re-ingestion overwrite rather than duplicate.

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

## Development

```bash
pytest                          # full suite
pytest -m "not integration"     # fast tests only, no network
pytest --cov=rag_agent          # with coverage

ruff check . && ruff format .   # lint and format
mypy                            # type check
```

Unit tests cover the pure logic — chunking, the calculator, settings, the
service loop with a fake model — and need no API key. Tests marked
`integration` hit the real embedding API and are skipped without one.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `O índice está vazio` | Run `rag ingest` |
| `Pasta de dados não encontrada` | Check `DATA_DIR` with `rag status` |
| OpenAI authentication error | Check `OPENAI_API_KEY` in `.env` |
| Nonsense answers after changing models | Delete `.chroma/` and re-ingest |
| Answers missing detail | Raise `RETRIEVAL_K` or `CHUNK_SIZE` |
| Broken accents on Windows | `set PYTHONIOENCODING=utf-8` |

---

## License

MIT.
