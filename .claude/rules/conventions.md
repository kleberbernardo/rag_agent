# Conventions and anti-patterns

## Language

**Everything written for a developer is in English. Everything written for the
person using the running program is in Portuguese.**

| What | Language |
|---|---|
| Identifiers: functions, classes, variables | English |
| Docstrings and comments | English |
| `CLAUDE.md` and every file in `.claude/rules/` | English |
| `README.md` and `docs/` | English |
| Test names and test docstrings | English |
| CLI output and error messages | **Portuguese** |
| API error details the caller reads | **Portuguese** |
| `.env.example` comments | **Portuguese** |
| Commit messages | **Portuguese** |

**No em dashes anywhere in the README or the rules.** They are not normal
punctuation in Brazilian Portuguese and they read as generated text. Use a
comma, a colon or a full stop.

---

## Anti-patterns confirmed by the project owner

These two were named explicitly. They are not theory.

### A. Do not add more commands and options

**What happened:** one round of work ended with several new evaluation
commands, each with its own flags. The reaction was literal: *"ta extremamente
confuso e não entendo nada, vc criou um monte de comando novo"*.

**The rule:** before adding a command or a flag, ask whether the behaviour can
be **detected** instead of **declared**. `rag eval` works out for itself
whether Langfuse is configured; there is no `--langfuse`.

**Warning sign:** if explaining a command needs a table comparing it to another
command, you built one command too many.

### C. Do not invent. Use what the market uses.

**What the owner said:** *"não quero inventar nada"*, *"vamos usar o que o
mercado usa, ver na internet qual o padrão"*.

**The rule:** where an established practice exists, use it and name it. RRF
with constant 60 is the value from the paper the method comes from. `unaccent`
ahead of the stemmer is the standard Postgres recipe for Portuguese.
`pool_pre_ping` is SQLAlchemy's own recommendation.

**Where no standard is obvious:** look it up before deciding, and record what
you found in [decisions.md](decisions.md).

**Warning sign:** you are about to write an algorithm that would need a name of
its own. It almost certainly already exists and already has one.

---

## Comments

**A comment explains why, never what.** A comment that restates the line below
it gets deleted.

The ones that survive record a measurement, a constraint, or a decision the
code cannot show:

```python
# 8 rather than 4: the evaluation suite scored 82% at k=4 and 93% at k=8
# on the same dataset. The corpus has many near-identical clauses, so a
# narrow window keeps landing on the neighbouring deadline.
retrieval_k: int = Field(default=8, gt=0)
```

That is the standard across the whole project. Keep it when editing.

---

## Tests

**A test name is a sentence:**

```python
def test_a_deep_hit_in_one_list_can_beat_a_shallow_miss_in_the_other(self) -> None:
```

**A test docstring says why the case matters**, not what the code does:

```python
def test_it_folds_accents(self) -> None:
    """Portuguese writes the same word both ways often enough to matter."""
```

**Classes group by behaviour**, not by method under test: `TestPoolWidth`,
`TestStageOrder`, `TestDistances`.

---

## Claims

**A number that reaches the README or a commit message comes from a run, not
from an estimate.**

Precedent: the evaluation once dropped to 21% after a chunking change. The
cause was a metric regex that broke, not the chunking. It was caught only
because `faithfulness` went **up** while `retrieval` collapsed, which is
impossible if retrieval had genuinely got worse.

If you did not measure it, say that you did not.

---

## Before finishing a change

**The target is `.`, not a list of folders.** CI runs `ruff check .` and
`ruff format --check .` over the whole repository, and a Python file outside
`src` and `tests` (`docs/diagrams/translate.py`, for one) sails past a check
scoped to those two and breaks the build on three platforms.

```bash
ruff format . && ruff check . && mypy && pytest -m "not integration"
```

That is the same set CI runs, and it takes about 40 seconds. During the work,
run only the test files that changed.

The integration suite needs a database and runs serially:

```bash
docker compose up -d postgres
alembic upgrade head
pytest -m integration -n 0
```

Serially because those tests share one database, and on an empty one several
workers race to create the tables langchain-postgres makes on first write.
