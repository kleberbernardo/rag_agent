# The agent and its tools

## The graph

`agent/service.py::build_agent` builds a LangGraph state graph through
LangChain's `create_agent`:

```
__start__ ──▶ model ⇄ tools ──▶ __end__
```

The model reads the question, may emit a tool call, the tool runs, the result
comes back as a message, and the model reads it and decides again. It ends when
the model stops calling tools and writes prose.

**Why an agent and not a plain pipeline:**

| Plain RAG | This project |
|---|---|
| Always retrieves once | Decides whether to retrieve at all |
| One query per question | Can retry with different search terms |
| Retrieval only | Chooses among several tools |

`recursion_limit=10` bounds the loop.

## The search budget: do not move it

The search tool is wrapped in a closure that counts calls:

```python
def build_search_tool() -> StructuredTool:
    budget = get_settings().max_searches_per_turn
    used = 0

    def search_with_budget(question: str) -> str:
        nonlocal used
        used += 1
        if used > budget:
            return _BUDGET_SPENT.format(used=budget)
        return search_documentation(question)
```

**Three things here are load bearing:**

1. **The counter is a closure, not a ContextVar.** A ContextVar was tried and
   does not work: LangGraph runs tools in its own context and the value does
   not propagate.

2. **`ChatSession.send()` rebuilds the agent every turn**, which is what resets
   the budget. Building the agent once and reusing it would let the budget run
   out across a conversation.

3. **The budget exists because the search never reports finding nothing.** It
   always returns its k nearest chunks. A question the corpus cannot answer
   therefore makes the model reword and search forever.

A distance threshold was measured as the alternative and rejected: the worst
valid question scores 0.97 and the best invalid one 0.84, so the ranges
overlap and no threshold separates them.

## Token accounting

`ChatSession.send()` marks `turn_start` before invoking. Without it, token
metrics count the whole conversation history again on every turn.

## Tools

A tool is a plain Python function. The model never sees the body, only the
name, the signature and the description. **The description is the contract**,
which is why it is written in the same language as the answers and built from
`KNOWLEDGE_DOMAIN`.

| Tool | Module |
|---|---|
| `search_documentation` | `tools/documentation.py` |
| `calculate` | `tools/calculator.py` |

Tools are assembled by `build_tools()` rather than held in a constant, because
the search tool's description depends on settings read at runtime.

**To add a tool:** write it in its own module, register it in `build_tools()`,
and put its description in `prompts/templates.py` so it can be managed in
Langfuse like the others.

## Sessions

`ChatSession` holds the message history. `ask()` is a one-off wrapper around a
single-turn session.

**A `ChatSession` cannot be pickled.** The compiled graph holds local closures,
and pickling fails with `Can't get local object
'CompiledStateGraph.attach_node.<locals>._get_updates'`. Redis storage works
around this by persisting only `messages_to_dict()` as JSON and rebuilding the
session on read. See [api.md](api.md).
