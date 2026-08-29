# RAG Agent — Assistente da documentação Nimbus

Agente de IA que responde perguntas sobre uma base de documentação interna,
buscando os trechos relevantes antes de responder e citando a fonte.

O produto documentado neste repositório é o **Nimbus**, uma plataforma fictícia
de observabilidade. Trocar a base de conhecimento é só trocar os arquivos de
`data/` e rodar a ingestão de novo — nenhuma linha de código muda.

---

## Índice

- [O que o projeto faz](#o-que-o-projeto-faz)
- [Como funciona](#como-funciona)
- [Instalação](#instalação)
- [Configuração](#configuração)
- [Uso](#uso)
- [Exemplos reais](#exemplos-reais)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Ajustes de comportamento](#ajustes-de-comportamento)
- [Testes e qualidade](#testes-e-qualidade)
- [Solução de problemas](#solução-de-problemas)

---

## O que o projeto faz

Um modelo de linguagem sozinho não conhece a sua documentação interna e, quando
perguntado sobre ela, inventa. Este projeto resolve isso com **RAG**
(_Retrieval-Augmented Generation_): antes de responder, o sistema busca os
trechos relevantes nos seus documentos e entrega esses trechos ao modelo como
contexto obrigatório.

A diferença aqui é que não se trata de um RAG linear, e sim de um **agente**:

| RAG simples | Agente (este projeto) |
|---|---|
| Sempre busca uma vez, depois responde | **Decide** se precisa buscar |
| Uma consulta por pergunta | Pode buscar de novo com outros termos |
| Só sabe buscar | Escolhe entre múltiplas ferramentas |

Ferramentas disponíveis ao agente hoje:

- **Busca na documentação** — busca semântica (por significado, não por
  palavra exata) na base indexada.
- **Calculadora** — avaliador aritmético seguro. Modelos de linguagem erram
  contas; esta ferramenta não erra. Total anual de um plano, rateio, percentual
  de excedente: tudo passa por ela.

O agente é instruído a **nunca responder de memória** sobre o produto e a
**citar o arquivo de origem** em toda resposta. Quando a informação não está na
base, ele diz que não encontrou em vez de inventar.

---

## Como funciona

O sistema tem duas fases independentes.

### Fase 1 — Indexação (offline, roda com `rag ingest`)

```
data/*.md ──▶ carregar ──▶ quebrar em pedaços ──▶ virar vetores ──▶ .chroma/
              (loader)      (chunk 1000 chars,     (embeddings         (banco
                             overlap 200)           OpenAI)             local)
```

O **overlap** de 200 caracteres existe para que uma ideia partida entre dois
pedaços continue inteira em pelo menos um deles.

Cada pedaço recebe um **ID determinístico** (hash do conteúdo + origem). Por
isso a ingestão é **idempotente**: rodar duas vezes sobrescreve os mesmos
registros em vez de duplicar o índice.

### Fase 2 — Consulta (online, roda com `rag ask` ou `rag chat`)

```
pergunta ──▶ agente decide ──▶ chama ferramenta ──▶ lê o resultado
                  ▲                                      │
                  └──────────── repete se precisar ◀──────┘
                                       │
                                       ▼
                            resposta com a fonte citada
```

A busca é **semântica**: a pergunta vira um vetor pelo mesmo modelo de
embeddings usado na indexação, e o banco devolve os pedaços mais próximos nesse
espaço. Por isso "quanto custa o plano do meio" encontra o trecho do plano
Growth, mesmo sem a palavra "Growth" aparecer na pergunta.

> **Importante:** o modelo de embeddings tem que ser o **mesmo** na indexação e
> na busca. Se você trocar `EMBEDDING_MODEL`, apague `.chroma/` e reindexe —
> vetores de modelos diferentes não são comparáveis entre si.

---

## Instalação

**Requisitos:** Python 3.12+ e uma chave da API da OpenAI.

```bash
# 1. Ambiente virtual
python -m venv .venv

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
# Linux / macOS
source .venv/bin/activate

# 2. Instalar o projeto em modo editável (cria o comando `rag`)
pip install -e ".[dev]"

# 3. Configurar a chave
cp .env.example .env      # Windows: copy .env.example .env
```

Instalar com `-e` (editável) significa que suas alterações no código valem na
hora, sem reinstalar.

---

## Configuração

Todos os ajustes vivem no arquivo `.env`, na raiz do projeto. Ele **nunca** vai
para o repositório — use o `.env.example` como modelo.

| Variável | Padrão | O que faz |
|---|---|---|
| `OPENAI_API_KEY` | — | **Obrigatória.** Sua chave da OpenAI. |
| `CHAT_MODEL` | `gpt-4o-mini` | Modelo que conversa e decide as ferramentas. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Modelo que converte texto em vetores. |
| `TEMPERATURE` | `0.0` | `0` = determinístico. Em RAG queremos fidelidade ao documento, não criatividade. |
| `CHUNK_SIZE` | `1000` | Tamanho máximo de cada pedaço, em caracteres. |
| `CHUNK_OVERLAP` | `200` | Caracteres repetidos entre pedaços vizinhos. |
| `RETRIEVAL_K` | `4` | Quantos trechos a busca traz por pergunta. |
| `DATA_DIR` | `data/` | Onde ficam seus documentos. |
| `VECTOR_STORE_DIR` | `.chroma/` | Onde o índice é gravado em disco. |
| `COLLECTION_NAME` | `rag_agent_docs` | Nome do conjunto dentro do banco. |

A configuração é validada no boot: valor inválido derruba a aplicação
imediatamente, com mensagem clara, em vez de falhar silenciosamente no meio de
uma consulta.

---

## Uso

### `rag ingest` — construir o índice

Lê tudo de `data/`, quebra em pedaços e grava no banco vetorial.
**Rode isto antes de qualquer pergunta**, e sempre que alterar os documentos.

```bash
rag ingest
rag ingest --verbose    # mostra o que cada etapa está fazendo
```

Formatos aceitos: `.md`, `.txt`, `.markdown`, `.rst` e `.pdf` (um documento por
página). A varredura é recursiva; arquivos de outros tipos são ignorados sem
erro.

### `rag ask` — pergunta única

```bash
rag ask "quanto custa o plano Growth?"
rag ask "qual o total anual do Growth?" --trace
```

A flag `--trace` mostra o raciocínio: quais ferramentas o agente decidiu
chamar, com quais argumentos e o que cada uma devolveu. É a melhor forma de
entender por que uma resposta saiu como saiu.

### `rag chat` — conversa contínua

```bash
rag chat
rag chat --trace
```

Mantém memória entre as perguntas — dá para dizer "e o Starter?" que ele
entende o assunto anterior. Saia com `sair`, `exit` ou `Ctrl+C`.

### `rag status` — diagnóstico

```bash
rag status
```

Mostra a configuração ativa e quantos pedaços estão indexados. Primeira coisa a
rodar quando algo parece errado.

---

## Exemplos reais

**Pergunta direta — uma ferramenta:**

```
$ rag ask "qual o limite de tamanho de um evento de log?"

╭─ resposta ───────────────────────────────────────────╮
│ O tamanho máximo de um evento de log é 256 KB.       │
│ (fonte: produto.md)                                  │
╰──────────────────────────────────────────────────────╯
ferramentas usadas: search_documentation
```

**Pergunta com conta — duas ferramentas encadeadas:**

```
$ rag ask "quanto custa o Growth por ano?" --trace

╭─ raciocínio ─────────────────────────────────────────╮
│ [VOCÊ] quanto custa o Growth por ano?                │
│ [AGENTE decide] chamar search_documentation(...)     │
│ [FERRAMENTA] -> Growth: R$ 890 por mês...            │
│ [AGENTE decide] chamar calculate({'expr': '890*12'}) │
│ [FERRAMENTA] -> 10680                                │
╰──────────────────────────────────────────────────────╯
╭─ resposta ───────────────────────────────────────────╮
│ O plano Growth custa R$ 890 por mês, o que dá        │
│ R$ 10.680 por ano. (fonte: produto.md)               │
╰──────────────────────────────────────────────────────╯
```

Repare que o agente **não fez a conta de cabeça**: ele buscou o preço e
delegou a multiplicação para a calculadora.

**Pergunta fora da base — o agente admite:**

```
$ rag ask "o Nimbus integra com o Datadog?"

╭─ resposta ───────────────────────────────────────────╮
│ Não encontrei isso na documentação.                  │
╰──────────────────────────────────────────────────────╯
```

---

## Estrutura do projeto

```
rag-agent/
├── README.md              este arquivo
├── pyproject.toml         dependências, comando `rag`, config de lint e testes
├── .env.example           modelo de configuração (copie para .env)
├── .gitignore
├── main.py                ponto de entrada
│
├── src/rag_agent/         código-fonte
│   ├── config.py          configuração central, validada no boot
│   ├── types.py           tipos de domínio (AnswerResult, SearchHit, ToolCall)
│   ├── providers/         clientes de LLM e embeddings (isola a OpenAI)
│   ├── prompts/           instruções permanentes do agente
│   ├── indexing/          carregar, quebrar e indexar documentos
│   ├── tools/             ferramentas que o agente pode chamar
│   ├── agent/             construção do agente e orquestração
│   ├── utils/             logging
│   └── cli.py             interface de linha de comando
│
├── tests/
│   ├── unit/              lógica pura, sem rede
│   └── integration/       fluxos com banco vetorial e agente
│
├── data/                  base de conhecimento (seus documentos)
├── logs/                  saída de log (não versionada)
└── docs/                  material de apoio
```

**Onde mexer para cada coisa:**

| Quero... | Mexo em |
|---|---|
| Trocar a documentação | `data/` + `rag ingest` |
| Mudar como o agente se comporta | `src/rag_agent/prompts/` |
| Adicionar uma ferramenta nova | `src/rag_agent/tools/` |
| Ajustar chunking ou busca | `.env` |
| Trocar de provedor de LLM | `src/rag_agent/providers/` |

---

## Ajustes de comportamento

**As respostas vêm incompletas** — aumente `RETRIEVAL_K` (mais trechos por
pergunta) ou `CHUNK_SIZE` (pedaços maiores, mais contexto em cada um). Ambos
aumentam o custo por consulta.

**O agente cita a fonte errada** — provável overlap alto demais colando
assuntos vizinhos. Reduza `CHUNK_OVERLAP`.

**O agente responde de memória em vez de buscar** — o system prompt em
`prompts/` é o lugar de corrigir. É lá que ficam as regras de comportamento.

**Quero adicionar uma ferramenta** — escreva uma função com o decorador `@tool`
e registre-a na lista `TOOLS`. A **docstring é o contrato**: o modelo não vê o
corpo da função, só o nome, a assinatura e a docstring. É por ela que ele decide
quando usar a ferramenta.

---

## Testes e qualidade

```bash
pytest                          # tudo
pytest -m "not integration"     # só os testes rápidos, sem rede
pytest --cov=rag_agent          # com cobertura

ruff check .                    # lint
ruff format .                   # formatação
mypy                            # checagem de tipos
```

Os testes marcados com `integration` tocam o banco vetorial ou a API e são
mais lentos. Os testes unitários cobrem a lógica pura — chunking, calculadora,
configuração — e rodam em menos de um segundo, sem chave de API.

---

## Solução de problemas

| Sintoma | Causa provável | Correção |
|---|---|---|
| `O índice está vazio` | Ingestão nunca rodou | `rag ingest` |
| `Pasta de dados não encontrada` | `DATA_DIR` aponta pro lugar errado | Confira o `.env` com `rag status` |
| Erro de autenticação da OpenAI | Chave ausente ou inválida | Confira `OPENAI_API_KEY` no `.env` |
| Respostas sem sentido após trocar de modelo | `EMBEDDING_MODEL` mudou | Apague `.chroma/` e rode `rag ingest` |
| Acentos quebrados no terminal Windows | Encoding do console | `set PYTHONIOENCODING=utf-8` |
| `chunk_overlap deve ser menor que chunk_size` | Configuração inválida | Ajuste no `.env`; overlap ≥ chunk trava a quebra |

---

## Licença

MIT.
