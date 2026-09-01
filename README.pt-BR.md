# RAG Agent

[![CI](https://github.com/kleberbernardo/rag_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/kleberbernardo/rag_agent/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![English](https://img.shields.io/badge/read_in-english-0057b7.svg)](README.md)

Um agente de IA de linha de comando que responde perguntas sobre os seus
próprios documentos.

Aponte para uma pasta de arquivos, rode a ingestão e pergunte em linguagem
natural. O agente recupera os trechos relevantes antes de responder e cita o
arquivo de onde tirou cada resposta. Quando a resposta não está nos seus
documentos, ele diz isso em vez de inventar uma.

- **Fundamentado**: as respostas vêm dos trechos recuperados, nunca da memória
  do modelo.
- **Com fonte**: toda resposta nomeia o arquivo de origem.
- **Agêntico**: o modelo decide quando buscar, pode buscar de novo com outros
  termos, e pode recorrer a outras ferramentas.
- **Um banco só**: Postgres com pgvector guarda os embeddings e responde à
  busca por palavra sobre as mesmas linhas, então um trecho e seu metadado são
  escritos numa transação só e não se separam.
- **Medido**: toda resposta informa latência, tokens consumidos e custo
  estimado, com rastreamento completo opcional no Langfuse.
- **Agnóstico de domínio**: o assunto vive na configuração, não no código.
  Troque a pasta, mude uma variável, reindexe.
- **Avaliado**: 29 perguntas medidas, incluindo algumas que o corpus não
  consegue responder. Hoje em 100%, com a ressalva de que uma das seis
  métricas é julgada por modelo e oscila.
- **Duas interfaces**: um CLI e uma API HTTP sobre a mesma camada de serviço,
  ambos num contêiner só.

---
## Arquitetura

![Arquitetura](docs/architecture.pt-BR.png)

Duas raias e uma coluna. **Construção** é tudo que acontece antes de existir
uma pergunta: ingestão, armazenamento, recuperação e a suíte medida.
**Operação** é uma pergunta e o que a cerca. **Governança** é a parte que
precisa sustentar o que as outras duas fizerem.

O diagrama é gerado a partir de
[`docs/diagrams/architecture.pt-BR.html`](docs/diagrams/architecture.pt-BR.html),
então ele é editado como código-fonte, não redesenhado.

### Onde o código mora

| Camada | Módulo | Responsabilidade |
|---|---|---|
| Interfaces | `cli.py`, `api/` | Traduzir entrada e saída. Nenhuma decisão. |
| Orquestração | `agent/` | Montar o grafo, rodar um turno, medi-lo. |
| Capacidades | `tools/` | O que o modelo pode chamar. |
| Recuperação | `indexing/` | Carregar, quebrar, vetorizar, buscar por significado e por palavra. |
| Segurança | `guardrails/` | O que é recusado na entrada, registrado na saída. |
| Provedores | `providers.py` | O único lugar em que a OpenAI aparece. |
| Comportamento | `prompts/` | As regras, buscadas no Langfuse ou lidas de `templates.py`. |
| Medição | `evaluation/` | Medir o agente, localmente ou na plataforma. |

As duas interfaces se apoiam em `agent/service.py`, então nenhuma delas guarda
orquestração própria e uma terceira é um invólucro, não uma reescrita. Os
guardrails rodam ali também, o que cobre toda interface por construção.

### Técnicas

| Técnica | Onde | Por que está aqui |
|---|---|---|
| **RAG agêntico** | `agent/` | Um pipeline recupera uma vez e responde. Aqui o modelo decide se recupera, e pode tentar de novo com outros termos. |
| **Busca híbrida** | `indexing/` | Um embedding acompanha paráfrase; a busca por palavra acha `Art. 70`. Medido na mesma pergunta: posição 31 pelo embedding, posição 5 por palavra. |
| **Reciprocal Rank Fusion** | `hybrid.py` | Funde por posição, não por nota, porque distância de cosseno e nota de busca textual não estão na mesma escala. |
| **Chunking adaptativo** | `splitter.py` | Por artigo, caindo para caractere abaixo de três cabeçalhos. Medido: 93% por caractere, 97% por artigo. |
| **Ingestão idempotente** | `vector_store.py` | O id é `sha256(coleção + origem + texto)`, então reindexar sobrescreve e uma fila pode reentregar em segurança. |
| **Recuperação em dois estágios** | `search()` | A recuperação é julgada por recall, a reordenação por precisão. O conjunto só alarga quando alguma coisa vai estreitá-lo. |
| **LLM como juiz** | `evaluation/judge.py` | Saída estruturada contra uma rubrica que é, ela própria, um prompt gerenciado. |
| **Varredura de injeção indireta** | `guardrails/injection.py` | Um trecho recuperado é lido do jeito que o system prompt é lido. Varrido na ingestão, uma vez por trecho. |
| **Gestão de prompts** | `prompts/` | Quatro prompts sob o label `production`. Mover o label é um rollback sem deploy. |
| **Falhar rápido com remédio** | em todo lugar | Toda mensagem de erro nomeia o comando que resolve. |

### Stack

| Camada | Ferramenta | Nota |
|---|---|---|
| Orquestração | LangChain 1.3, LangGraph 1.2 | Através de `create_agent`, nunca `langgraph` direto |
| Modelo | OpenAI `gpt-4o-mini`, `text-embedding-3-small` | Trocar de provedor reescreve `providers.py` e mais nada |
| Vetor e texto | Postgres 17, pgvector, FTS nativo | Um banco, uma transação |
| Reordenação | `sentence-transformers`, `BAAI/bge-reranker-v2-m3` | Construída, medida, desligada por padrão |
| Guardrails | LLM Guard, presidio, `katanemolabs/Arch-Guard` | O modelo de injeção foi escolhido medindo |
| Observabilidade | Langfuse 4.15 | Traces, notas, datasets, gestão de prompts |
| HTTP | FastAPI, Uvicorn | Workers configuráveis; `/health` e `/ready` separados |
| Limite de taxa | `limits` | Janela móvel, compartilhada pelo Redis |
| Migrações | Alembic | A aplicação verifica, nunca aplica |
| Sessões | Redis, ou no processo | Só o histórico de mensagens viaja |
| CLI | Typer, Rich | Testado com `CliRunner`, sem subprocesso |
| Configuração | Pydantic Settings | Todo valor ajustável, validado no boot |
| Qualidade | pytest, pytest-xdist, ruff, mypy | Os testes de unidade não exigem nada rodando; os de integração rodam contra um Postgres real |
| CI | GitHub Actions | Linux e Windows, mais uma execução semanal da avaliação |

---
## Instalação

Requer Python 3.12+ e uma chave de API da OpenAI.

**1. Crie o ambiente virtual e ative**

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

O seu prompt agora começa com `(.venv)`. É assim que você sabe que funcionou.

**2. Instale o projeto**

```bash
pip install -e ".[dev]"
```

A flag `-e` faz mudanças no código valerem na hora, e a instalação registra o
comando `rag`.

**3. Defina a sua chave de API**

```bash
cp .env.example .env        # Windows: copy .env.example .env
```

Depois edite o `.env`:

```
OPENAI_API_KEY=sk-...
```

---
## Rodando os comandos

> **O comando `rag` só existe enquanto o ambiente virtual está ativo.**
> A ativação vale para aquela janela de terminal apenas. Abriu uma nova, tem
> que ativar de novo. Esse é de longe o motivo mais comum de o `rag` "não
> funcionar".

Toda sessão começa assim:

```powershell
.\.venv\Scripts\Activate.ps1     # Windows; source .venv/bin/activate nos outros
$env:PYTHONIOENCODING='utf-8'    # só Windows, mantém a acentuação da saída
```

`rag: command not found` (ou `O termo 'rag' não é reconhecido`) sempre quer
dizer que o ambiente não está ativo. Duas saídas:

```powershell
.\.venv\Scripts\Activate.ps1     # ative, depois use `rag ...`
.\.venv\Scripts\rag.exe chat     # ou chame o executável direto, sem ativar
```

Se o PowerShell recusar o script de ativação com *"a execução de scripts foi
desabilitada neste sistema"*, libere uma vez para o seu usuário:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Nunca instalou o pacote? `python main.py chat` funciona da raiz do projeto sem
o comando `rag`.

---
## Comandos

Nove comandos. Três deles são o que você usa no dia a dia.

| Comando | O que faz | Flags |
|---|---|---|
| `rag ingest` | Lê `data/`, quebra e indexa. Rode uma vez, e de novo quando os documentos mudarem. | `--reset`, `-v` |
| `rag ask "..."` | Uma pergunta. | `--trace`, `-v` |
| `rag chat` | Uma conversa com memória. | `--trace`, `-v` |
| `rag status` | A configuração ativa e quantos pedaços estão indexados. | |
| `rag sources` | Lista os documentos indexados, ou tira um deles do índice. | `--remove <arquivo>`, `--yes` |
| `rag eval` | Mede o agente contra as 29 perguntas. | Veja a tabela abaixo |
| `rag serve` | Sobe a API HTTP. | `--host`, `--port`, `--workers`, `--reload`, `-v` |
| `rag prompt show` \| `push` | Lê o prompt em vigor; publica os locais. | `--message`, `-v` |
| `rag dataset push` | Envia o dataset de avaliação para o Langfuse. | `--dataset`, `-v` |

`--verbose` e `-v` significam a mesma coisa em todo comando que os aceita, e
sobem o nível de log daquela execução.

### `rag eval` por inteiro

Um comando. Nada a escolher sobre onde ele roda:

```bash
rag eval
```

| Com o Langfuse configurado | Sem |
|---|---|
| As perguntas vêm do dataset de lá | As perguntas vêm de `evals/dataset.json` |
| As notas voltam, uma por métrica por pergunta | Um relatório é gravado em `evals/results/` |

Dos dois jeitos o agente e as métricas rodam nesta máquina. Nenhuma plataforma
executa a sua aplicação: a própria documentação do Langfuse é explícita ao
dizer que os avaliadores dele "pontuam os dados já registrados nos seus traces"
e "nunca reexecutam a sua aplicação". Essa divisão é a padrão, e é o que a
integração entre RAGAS e Langfuse descreve: o framework calcula a métrica, a
plataforma guarda a nota ao lado do trace que produziu a resposta.

O que acontece numa execução:

```
1. lê as 29 perguntas             Langfuse, ou o arquivo
2. responde cada uma              esta máquina, sempre
3. mede seis métricas             esta máquina, sempre
4. envia as notas                 Langfuse, uma por métrica por pergunta
5. imprime a tabela               este terminal, sempre
```

| Flag | Efeito |
|---|---|
| `--no-judge` | Pula `faithfulness`, a única métrica que custa tokens para calcular |
| `--limit N` | Só as N primeiras perguntas |
| `--min-score 0.9` | Sai com código diferente de zero abaixo disso |
| `--max-cost 0.05` | Sai com código diferente de zero acima disso |
| `--name` | Dá nome à execução na plataforma |
| `--compare <relatório>` | Compara com um relatório local anterior |

### Lendo no Langfuse

Três lugares guardam a mesma execução, em resoluções diferentes:

| Onde | O que você vê |
|---|---|
| **Experiments** | Uma linha por pergunta, as métricas como colunas. Comece aqui. |
| **Scores** | Uma linha por métrica por pergunta, cru. 29 × 6 linhas, não um resumo. |
| **Tracing** | Uma pergunta por inteiro: a busca, os trechos, as chamadas de ferramenta, o custo. |

O menu **Evaluators** fica vazio de propósito. Ele guarda juízes que o Langfuse
roda nos servidores dele sobre tráfego real, configurados por formulário. O
juiz deste projeto vive em `evaluation/judge.py`, então a rubrica dele é
versionada, testável e legível no repositório, e roda offline. São duas
funcionalidades diferentes que dividem uma palavra.

---
## Uso

Todos os comandos abaixo assumem o ambiente ativo.

### 1. Coloque os seus documentos

Jogue arquivos em `data/`. Suportados: `.md`, `.txt`, `.markdown`, `.rst` e
`.pdf`. Subpastas são varridas recursivamente; o resto é ignorado.

O repositório vem com um corpus real para você experimentar na hora: três
resoluções consolidadas da CVM, o regulador do mercado de capitais brasileiro.
204 páginas sobre adequação de produtos, divulgação de informação relevante e
ofertas públicas. A procedência está em `docs/knowledge-base-sources.md`.

Nada no código depende delas. Para usar os seus, esvazie `data/`, defina
`KNOWLEDGE_DOMAIN` no `.env` e rode `rag ingest --reset`.

### 2. Construa o índice

```bash
rag ingest
rag ingest --verbose
```

Rode uma vez, e de novo sempre que os documentos mudarem. A ingestão é
idempotente: rodar duas vezes atualiza os mesmos registros em vez de
duplicá-los.

### 3. Pergunte

```bash
rag ask "o que e o dever de verificacao da adequacao dos produtos?"
rag ask "qual o percentual maximo do lote suplementar?" --trace
```

`--trace` imprime o raciocínio do agente: quais ferramentas ele escolheu, com
quais argumentos, e o que cada uma devolveu.

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

Toda resposta fecha com o que ela custou: latência de relógio, tokens
separados entre entrada e saída, quantas ferramentas rodaram, e um preço
estimado. É medido localmente a partir do relatório de uso do próprio
provedor, sem conta e sem serviço externo. Um modelo sem preço listado não
mostra estimativa nenhuma, em vez de um número confiante e errado.

O agente não fez a conta sozinho. Ele delegou a multiplicação à calculadora, e
citou a página de onde tirou o limite.

As citações chegam ao artigo, não só ao arquivo, porque a quebra por artigo
registra de qual `Art. N` cada trecho veio:

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

Esse artigo sozinho carrega cinco prazos diferentes ao longo dos parágrafos.
Cortar a cada 1000 caracteres separava um do outro, e o agente respondia com o
prazo vizinho. `CHUNK_STRATEGY=articles` resolveu isso.

### 4. Ou converse

```bash
rag chat
rag chat --trace        # acrescenta as ferramentas usadas e o custo de cada turno
```

Mantém contexto entre os turnos, então perguntas de acompanhamento funcionam
sem repetir o assunto. Saia com `sair`, `exit` ou `Ctrl+C`. Todo comando
também aceita `--verbose`, que liga o log do que cada módulo está fazendo.

```
você > o que caracteriza uma informacao relevante?
agente > É qualquer decisão ou fato que possa influir de modo ponderável
         na cotação dos valores mobiliários...
         (fonte: cvm-resolucao-44-informacoes-relevantes.pdf)

você > e quem tem o dever de divulgar?     ← não precisa repetir o assunto
agente > O Diretor de Relações com Investidores...
         (fonte: cvm-resolucao-44-informacoes-relevantes.pdf)

você > sair
```

### Diagnóstico

```bash
rag status
```

Mostra a configuração ativa e quantos pedaços estão indexados. Rode isso
primeiro sempre que algo parecer errado.

---
## Configuração

Tudo mora no `.env`. Copie o `.env.example` e edite. Os valores são validados
no boot, então uma configuração inválida para o programa na hora com uma
mensagem clara, em vez de falhar no meio de uma consulta.

| Variável | Padrão | Para que serve |
|---|---|---|
| `OPENAI_API_KEY` | nenhum | **Obrigatória.** |
| `CHAT_MODEL` | `gpt-4o-mini` | Modelo que raciocina e escolhe ferramentas. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Modelo que transforma texto em vetor. |
| `TEMPERATURE` | `0.0` | `0` é determinístico, o certo para respostas fundamentadas. |
| `CHUNK_STRATEGY` | `articles` | `articles` dá a cada `Art. N` um pedaço próprio; `characters` corta por tamanho. |
| `CHUNK_SIZE` | `1000` | Máximo de caracteres por pedaço. |
| `ARTICLE_MAX_CHARS` | `4000` | Teto acima do qual um único artigo é quebrado mais. |
| `CHUNK_OVERLAP` | `200` | Caracteres repetidos entre pedaços vizinhos. |
| `SEARCH_STRATEGY` | `hybrid` | `hybrid` funde a busca textual do banco com o embedding; `vector` usa só o embedding. |
| `RERANK_STRATEGY` | `none` | `cross_encoder` acrescenta uma segunda passada que reordena o que foi recuperado. |
| `RERANK_MODEL` | `BAAI/bge-reranker-v2-m3` | O cross-encoder a carregar. Multilíngue, aberto, roda local. |
| `RERANK_CANDIDATES` | `24` | Quantos candidatos o reordenador lê. Cada um é uma passada de modelo, então é o botão de latência. |
| `RATE_LIMIT` | `60/minute` | Teto por chamador. Vazio desliga. |
| `RATE_LIMIT_STORAGE` | nenhum | Onde ficam os contadores. Vazio é por processo; uma URL `redis://` é compartilhada. |
| `API_WORKERS` | `1` | Processos do Uvicorn. Um serializa toda requisição. |
| `RETRIEVAL_K` | `8` | Trechos recuperados por pergunta. |
| `MAX_SEARCHES_PER_TURN` | `3` | Quantas vezes o agente pode buscar numa mesma pergunta. |
| `GUARDRAILS_ENABLED` | `true` | Uma chave para a camada inteira. Para a suíte e para depurar, não para produção. |
| `GUARDRAIL_SCANNER` | `llm_guard` | `none` mantém as verificações aritméticas e pula os modelos. |
| `INJECTION_MODEL` | `katanemolabs/Arch-Guard` | O classificador de injeção. Trocar é configuração. |
| `SCAN_CORPUS_FOR_INJECTION` | `true` | Varre cada pedaço na ingestão, contra injeção indireta. |
| `MAX_QUESTION_CHARS` | `2000` | Mais longo que isso é ataque de custo antes de ser qualquer outra coisa. |
| `MAX_ANSWER_TOKENS` | `8000` | Registrado, não imposto: a resposta já existe. |
| `KNOWLEDGE_DOMAIN` | genérico | Sobre o que é o corpus. Injetado no system prompt e na descrição da ferramenta de busca. |
| `DATA_DIR` | `data/` | Onde os seus documentos ficam. |
| `LOG_DIR` | `logs/` | Onde o arquivo de log é escrito. |
| `DATABASE_URL` | `postgresql+psycopg://rag:rag@localhost:5432/rag` | Onde o índice mora. O driver é nomeado porque o SQLAlchemy assume psycopg2. |
| `DATABASE_POOL_SIZE` | `5` | Conexões mantidas abertas por processo. As réplicas multiplicam isso. |
| `DATABASE_MAX_OVERFLOW` | `10` | Conexões extras permitidas acima do pool sob carga. |
| `DATABASE_CONNECT_TIMEOUT` | `5` | Segundos antes de desistir de uma conexão. Sem isso o driver espera mais de dois minutos. |
| `EMBEDDING_DIMENSIONS` | `1536` | Largura da coluna de embedding. Precisa bater com o modelo. |
| `COLLECTION_NAME` | `rag_agent_docs` | Nome da coleção dentro do armazenamento. |
| `LANGFUSE_PUBLIC_KEY` | nenhum | Opcional. Liga o rastreamento quando definida junto da chave secreta. |
| `LANGFUSE_SECRET_KEY` | nenhum | Opcional. Veja [Observabilidade](#observabilidade). |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Região do Langfuse, por exemplo `https://us.cloud.langfuse.com`. |
| `PROMPT_LABEL` | `production` | Qual versão publicada do prompt o agente pega. |
| `PROMPT_CACHE_SECONDS` | `60` | Por quanto tempo um prompt buscado é reaproveitado. |
| `SESSION_BACKEND` | `memory` | `memory` guarda as conversas no processo; `redis` compartilha. |
| `REDIS_URL` | `redis://localhost:6379/0` | Onde o Redis mora, no modo `redis`. |
| `SESSION_TTL_SECONDS` | `3600` | Quanto tempo uma conversa parada sobrevive. |
| `API_KEY` | nenhum | Defina e toda requisição precisa do cabeçalho `X-API-Key`. |
| `MAX_RETRIES` | `3` | Tentativas quando o provedor limita a taxa ou está fora. |
| `REQUEST_TIMEOUT_SECONDS` | `60` | Teto de uma chamada ao provedor. |

---
## Como funciona

O sistema tem duas fases que nunca rodam ao mesmo tempo.

### Fase 1: ingestão (offline)

```
data/*  ──▶  carrega ──▶ quebra ──▶ vetoriza ──▶  Postgres
            (loader)   (splitter) (providers)  (vector_store)
```

**Carregar**. Cada arquivo vira um `Document` carregando o nome do arquivo
como metadado. A resposta final cita a origem a partir desse metadado. PDFs
viram um documento por página, então uma citação pode apontar um número de
página.

**Quebrar**. Duas estratégias, escolhidas por `CHUNK_STRATEGY`.

`characters` corta a cada `CHUNK_SIZE` caracteres, quebrando primeiro em
parágrafo, depois em linha, frase e palavra. Os pedaços se sobrepõem em
`CHUNK_OVERLAP` caracteres, para que uma ideia que cai em cima de uma fronteira
sobreviva inteira em pelo menos um deles.

`articles` dá a cada `Art. N` um pedaço próprio. Textos legais e regulatórios
já vêm divididos pelo autor, e cortar a cada 1000 caracteres separa uma regra
da exceção que a qualifica. O corpus que acompanha o projeto tem um artigo que
carrega cinco prazos diferentes ao longo dos parágrafos. Só um `Art.` com
maiúscula abre um artigo; `art. 36` em minúscula é uma referência cruzada
dentro da frase, e este corpus tem 138 delas contra 106 cabeçalhos de verdade.

É adaptativo: uma origem com menos de três cabeçalhos cai para caractere,
então um README comum na pasta sai ileso. As páginas de PDF são unidas antes
de quebrar, porque um artigo rotineiramente atravessa uma quebra de página.
Artigos acima de `ARTICLE_MAX_CHARS` são quebrados mais, porque anexos não
têm cabeçalho e um deles chegou como um bloco único de 148 mil caracteres.

Medido sobre o corpus que acompanha: **93% por caractere, 97% por artigo.**

**Vetorizar**. Cada pedaço é enviado ao modelo de embedding e volta como um
vetor: uma lista de números que posiciona aquele texto no espaço semântico.
Pedaços que significam coisas parecidas caem perto uns dos outros.

**Armazenar**. Os vetores são escritos no Postgres. Cada pedaço ganha um id
derivado de um hash da sua **coleção, origem e conteúdo**, então reindexar
sobrescreve em vez de duplicar. É isso também que torna a ingestão segura para
repetir a partir de uma fila, onde a mesma mensagem pode ser entregue mais de
uma vez.

> A coleção faz parte desse hash porque o id é a chave primária de uma tabela
> que todas as coleções compartilham. Derivado só do conteúdo, gravar um
> pedaço numa segunda coleção tirava a linha da primeira em silêncio, e a
> segunda reportava que nada foi escrito. Era invisível com uma coleção só, e
> foi encontrado apenas quando dois testes indexaram o mesmo material em
> coleções descartáveis próprias.

Postgres é o único modo. Um arquivo embutido seria uma coisa a menos para
rodar, e seria também uma segunda engine de armazenamento a manter se
comportando como a primeira, o que é um custo pago a cada mudança na
recuperação por uma conveniência que acaba no instante em que o corpus é
compartilhado.

Um banco inalcançável falha com uma mensagem que nomeia o endereço tentado e o
comando que o sobe, em vez de uma pilha de chamadas do driver. A senha é
removida de toda renderização da URL, incluindo essa mensagem.

### Por que Postgres

| | |
|---|---|
| **Dois recuperadores, um armazenamento** | Os vetores e o texto ficam nas mesmas linhas, então a busca por palavra não precisa de um segundo sistema nem de uma cópia que envelhece. |
| **Uma transação** | Um pedaço, seu metadado e seu vetor são escritos juntos ou não são escritos. |
| **Já está lá** | A maioria das organizações roda Postgres. Isso acrescenta uma extensão, não um banco para operar. |
| **Gerenciado em todo lugar** | RDS, Cloud SQL, Supabase e Neon oferecem pgvector. |
| **Depurável** | O índice é inspecionável com `SELECT`, não por uma API proprietária. |

Dois índices são construídos depois da primeira escrita, já que nenhum pode
existir antes das tabelas. `HNSW` na coluna de vetor é o índice de vizinho mais
próximo aproximado; sem ele o pgvector é exato, o que é correto e lê todas as
linhas. `GIN` na expressão de texto é o que evita que a busca por palavra
analise todo documento armazenado a cada consulta. Os dois são a diferença
entre um corpus de centenas e um de milhões.

O teto fica em algum ponto acima de dez milhões de vetores, ou em filtro pesado
de metadado com alta taxa de consulta. Passando disso, a resposta é uma engine
dedicada como o Qdrant, e a mudança é uma classe: nada na fusão, no agente ou
na avaliação sabe qual armazenamento respondeu.

### Fase 2: consulta (online)

```
pergunta ──▶ agente decide ──▶ roda ferramenta ──▶ lê o resultado
                   ▲                                     │
                   └────────── repete se precisar ◀──────┘
                                      │
                                      ▼
                          resposta, com a fonte citada
```

A pergunta é vetorizada pelo **mesmo modelo** usado na ingestão, e o
armazenamento devolve os pedaços mais próximos. É por isso que "quanto custa o
plano mais barato" acha o trecho certo mesmo quando nem "barato" nem "plano"
aparecem no texto. O casamento acontece no significado, não nas palavras.

Uma busca tem dois estágios, e só o primeiro roda sempre:

```
pergunta ──▶ recuperação ──▶ candidatos ──▶ [reordenação] ──▶ trechos
             larga, barata                  estreita, desligada por padrão
```

A recuperação decide o que está no conjunto e é julgada por a resposta estar
lá. A reordenação decide o que sai dele e é julgada pela melhor estar no topo.
Sem reordenador o conjunto é a resposta, então ele é recuperado exatamente na
largura pedida. Veja [Reordenação](#reordenação) para o motivo de o segundo
estágio estar desligado aqui.

> Mude `EMBEDDING_MODEL` e você precisa rodar `rag ingest --reset`, e ajustar
> `EMBEDDING_DIMENSIONS` para bater. Vetores de modelos diferentes não são
> comparáveis nem têm a mesma largura.

### Por que um agente, e não um pipeline

Um pipeline de RAG comum sempre recupera exatamente uma vez, e então responde.
Este deixa o modelo decidir:

| RAG comum | Este projeto |
|---|---|
| Sempre recupera uma vez | Decide se recupera |
| Uma consulta por pergunta | Pode tentar de novo com outros termos |
| Só recuperação | Escolhe entre várias ferramentas |

O laço é: o modelo lê a pergunta, pode emitir uma chamada de ferramenta, a
ferramenta roda, o resultado volta como mensagem, e o modelo lê e decide de
novo. Termina quando o modelo para de chamar ferramentas e escreve prosa.

### Ferramentas

Uma ferramenta é uma função Python comum que o modelo pode chamar. O modelo
nunca vê o corpo, só o nome, a assinatura e a docstring. **A docstring é o
contrato**: é como o modelo decide quando a ferramenta se aplica.

- `search_documentation`: busca semântica sobre os pedaços indexados.
- `calculate`: um avaliador aritmético seguro. Modelos de linguagem são pouco
  confiáveis em aritmética, então tudo que é numérico é delegado aqui. As
  expressões são analisadas em árvore sintática e verificadas contra uma lista
  do que é permitido, então uma string escrita pelo modelo nunca vira execução
  arbitrária de código.

Para acrescentar uma: escreva a função com o decorador `@tool` no módulo dela
dentro de `tools/`, e registre em `build_tools()`. É uma função e não uma
constante porque a descrição da ferramenta de busca é renderizada na hora da
chamada a partir de `KNOWLEDGE_DOMAIN`.

### Comportamento

As regras do agente vivem em `prompts/`: sempre recuperar antes de responder
sobre os documentos, responder apenas a partir dos trechos recuperados, admitir
quando algo está faltando, sempre citar a fonte, e nunca fazer conta de cabeça.
Publicar uma nova versão no Langfuse, ou editar `templates.py`, é como se muda
o comportamento do agente.

---

### O laço do agente

`create_agent` monta um grafo de estado do LangGraph e o devolve compilado. O
projeto nunca importa `langgraph` diretamente, e o grafo não é escrito à mão:
ele tem três nós e uma aresta condicional.

```
   __start__
       │
       ▼
   ┌────────┐
   │ modelo │ ◄─────────┐
   └───┬────┘           │
       │ condicional    │
   ┌───┴────────┐       │
   ▼            ▼       │
ferramentas  __end__    │
   │                    │
   └────────────────────┘
```

A aresta condicional carrega a ideia inteira. Depois que o modelo fala, o grafo
pergunta se ele pediu uma ferramenta:

- **sim** → roda `ferramentas`, devolve a saída para `modelo`
- **não** → `__end__`, a resposta é final

Esse ciclo é o que deixa o agente buscar, ler o que voltou, e decidir de novo.
Sem ele o fluxo é linear: recupera uma vez, responde, para.

O laço tem dois tetos, e os dois existem por causa da mesma pergunta: uma que o
corpus não consegue responder.

`MAX_SEARCHES_PER_TURN` interrompe a busca. Uma busca vetorial sempre devolve
os `k` pedaços mais próximos, por mais longe que estejam, então ela nunca
consegue reportar que não achou nada. O agente vê resultados em toda tentativa
e reformula a consulta indefinidamente. Passado o orçamento, a ferramenta
responde com uma instrução para concluir, e o agente diz que não encontrou o
assunto, que é o desfecho verdadeiro.

Um limiar de distância seria a correção óbvia e não funciona aqui. Medido neste
corpus, a pior pergunta válida tira 0,972 e a melhor inválida tira 0,840: as
faixas se sobrepõem, então qualquer corte recusa perguntas boas ou aceita
ruins.

Dez passos no grafo é o segundo teto, e a rede de proteção atrás do primeiro.
### Busca híbrida

Dois recuperadores rodam e as ordenações deles são fundidas.

Um embedding compara significado, que é o que deixa uma pergunta achar um
trecho sem nenhuma palavra em comum. Ele também espalha o sinal de um artigo
longo por tudo que aquele artigo discute, então uma frase que enuncia um prazo
fica abaixo do assunto principal do artigo.

A busca textual do Postgres compara palavras. Ela não acompanha paráfrase, e
não precisa quando a pergunta nomeia os termos que o texto usa.

Medido neste corpus, na pergunta em que a suíte falhou por semanas: o trecho
que enuncia o prazo de suspensão está na **posição 31 pelo embedding** e na
**posição 5 por palavra**.

As duas listas são fundidas por reciprocal rank fusion. Cada documento soma
`1 / (60 + posição)` nas listas em que aparece, então um trecho que os dois
recuperadores ranqueiam bem vence um que só um deles adora. Fundir por posição
e não por nota é o que torna isso possível: distância de cosseno e nota de
busca textual não estão na mesma escala e não podem ser somadas.

Cada recuperador é consultado por cinco vezes o número de trechos desejado, e a
lista fundida é cortada depois. Fundir duas listas curtas só premia o que os
dois recuperadores já concordavam, que é o que qualquer um deles acharia
sozinho; os trechos que valem acrescentar estão mais fundo em uma das listas.
Medido aqui, o prazo que faltava entra no top 8 com multiplicador cinco e não
com três.

`SEARCH_STRATEGY=vector` desliga a metade por palavra. Essa metade é um índice
GIN sobre as mesmas linhas, então não há segunda cópia a manter em dia nem nada
a reconstruir quando o armazenamento muda.

**O que isso consertou:** o último caso que falhava, e junto com ele
`correctness` e `faithfulness`. Toda métrica agora marca 100% sobre 29
perguntas.

**Quanto esse número vale:** as cinco métricas determinísticas são
reproduzíveis, então 100% ali significa 100% de novo amanhã. `faithfulness` é
julgada por modelo e oscila; uma execução em 100% não garante a próxima.

### Reordenação

Desligada por padrão. Esta seção é tanto sobre o porquê quanto sobre o como.

**O que é um reordenador.** Uma segunda passada que reordena os trechos que a
busca já recuperou. Ele não acha nada por conta própria.

```
recuperação ──▶ 24 candidatos ──▶ reordenador ──▶ 8 trechos ──▶ agente
   larga, barata                   estreito, caro
```

**Por que ele acerta mais.** Todo recuperador acima compara duas coisas através
de algo pré-calculado. Um trecho é vetorizado na ingestão, meses antes de a
pergunta existir, então o vetor dele comprime o texto sem saber o que vão
perguntar. Um cross-encoder lê a pergunta e o trecho juntos, numa passada só, e
responde direto: este trecho responde aquela pergunta.

É também por isso que ele é caro. Nada pode ser pré-calculado, então o custo é
uma passada de modelo por candidato, em toda pergunta.

| | Embedding | Cross-encoder |
|---|---|---|
| Lê o par junto | Não | Sim |
| Calculado quando | Na ingestão | Na hora da pergunta |
| Custo | Uma consulta | Uma passada por candidato |
| Escala para | Milhões de trechos | Dezenas |

**Por que está desligado aqui.** Um reordenador corrige precisão. Ele não
conserta um conjunto em que a resposta não está. A falha que esta suíte teve
por semanas era de recall: medido neste corpus, o trecho que enuncia o prazo de
suspensão estava na posição 31 de 590 pelo embedding. Com `RETRIEVAL_K=8`, o
reordenador receberia oito trechos que não continham a resposta, e devolveria
oito trechos que continuavam não contendo. Quem consertou foi a busca híbrida.

Ligar acrescentaria latência e dois gigabytes de dependência por um ganho
medido de nada, num corpus em que toda métrica já marca 100%.

**Como fica quando funciona.** Medido com o modelo padrão sobre cinco trechos
reais deste corpus, com a resposta colocada em último de propósito, como ela
chegaria de um conjunto amplo:

| Depois da reordenação | Era | Nota | Trecho |
|---|---|---|---|
| 1 | 5 | `+0.9723` | `§ 2º O prazo de suspensão da oferta não pode ser superior a 30 dias.` |
| 2 | 2 | `+0.2308` | `Art. 70. A SRE pode suspender ou cancelar, a qualquer tempo…` |
| 3 | 1 | `+0.0050` | `Art. 12. O lote suplementar não pode ultrapassar 15%…` |
| 4 | 3 | `+0.0004` | `Art. 25. O prospecto deverá ser elaborado…` |
| 5 | 4 | `+0.0001` | `Art. 3. Consideram-se atos de distribuição pública…` |

A distância entre os dois primeiros é a parte útil. O trecho que apenas
menciona suspensão tira 0,23; o que enuncia o prazo tira 0,97. Um embedding não
separa esses dois, porque ambos falam de suspender uma oferta.

**Quando ligar.** Quando o conjunto for largo o bastante para a resposta estar
nele mas não perto do topo. Essa é a condição normal em escala, e é por isso
que o formato de dois estágios existe: com milhões de trechos você precisa
recuperar cem ou mais para ter confiança no recall, e cem trechos não cabem num
prompt. O reordenador é o funil entre esses dois fatos.

```bash
RERANK_STRATEGY=cross_encoder rag ask "qual o prazo de suspensão?"
```

O pacote já está instalado: os guardrails precisam do torch, então o
reordenador custa quase nada em cima dele. Os pesos são um download de 2,2 GB
no primeiro uso.

O conjunto alarga sozinho quando ele é ligado: `RERANK_CANDIDATES` substitui
`RETRIEVAL_K` como largura da recuperação, porque um reordenador que recebe
exatamente o que devolve não tem entre o que escolher.

**Sobre a dependência.** Um cross-encoder local significa torch. Esse era o
argumento para mantê-lo opcional, e deixou de ser quando os guardrails
tornaram o torch obrigatório de qualquer jeito. Em escala a resposta não é nem
no processo nem opcional, é um serviço de reordenação próprio, com o modelo
carregado uma vez atrás de um endpoint em vez de uma vez por réplica da API. A
interface aqui é um método, então isso é uma classe, não uma reescrita.

**Sobre mandar texto para uma API.** O Cohere Rerank é o padrão comercial e é
muito bom. Ele também significa que o corpus sai da rede. Para uma instituição
regulada isso costuma encerrar a discussão, e é por isso que o modelo local é a
escolha padrão aqui.

---
## Guardrails

Três camadas na entrada, uma na saída. Elas rodam a partir de
`agent/service.py`, então o CLI e a API ficam cobertos por construção e uma
interface nova não tem como esquecer.

| Camada | Verifica | Ao falhar |
|---|---|---|
| Aritmética | Vazio, e tamanho contra `MAX_QUESTION_CHARS` | Recusa |
| Varredura | Segredos, e-mail, cartão, e **CPF, CNPJ, chaves de API** | Recusa |
| Injeção | Se a pergunta é uma instrução | Recusa |
| Saída | Citação presente, teto de tokens | **Registra uma ocorrência** |

**Uma pergunta é recusada antes de custar qualquer coisa. Uma resposta já foi
paga quando pode ser julgada**, então o que acontece com ela é um registro
anexado ao resultado, nunca uma exceção. A citação em especial é registro e não
recusa: uma recusa correta não cita nada, e este corpus tem quatro perguntas
que ele não consegue responder de propósito.

### LLM Guard, configurado e não usado como vem

O LLM Guard é o padrão e é feito para inglês. O próprio pacote declara
`ALL_SUPPORTED_LANGUAGES` como `["en", "zh"]`, e a lista de entidades padrão é
`US_SSN` e `US_BANK_NUMBER`. Medido aqui, antes de qualquer configuração:

| Pergunta | Veredito |
|---|---|
| "qual o prazo máximo de suspensão?" | **recusada**, confiança 1,00 |
| "what is the maximum suspension period?" | passou |
| "o que diz o Art. 70 da Resolução 160?" | **recusada**, leu 160 como número de conta |
| um CPF | **passou** |

Ele recusava toda pergunta real e perdia o único identificador que importa no
Brasil. O que consertou: descartar o scanner de injeção dele, que é só em
inglês, estreitar `entity_types` para os padrões que não dependem de idioma, e
acrescentar CPF, CNPJ e chaves de API por regex.

### O classificador de injeção foi escolhido medindo

Oito casos, quatro deles ataques, metade em português:

| Modelo | Acertos | Falsos positivos |
|---|---|---|
| **`katanemolabs/Arch-Guard`** | **7/8** | **0** |
| `testsavantai/prompt-injection-defender-large-v0` | 6/8 | 0 |
| `jackhhao/jailbreak-classifier` | 5/8 | 0 |
| `protectai/deberta-v3-base-prompt-injection-v2` | 5/8 | **3** |

A última linha é o padrão do LLM Guard. O Prompt Guard 2 da Meta é o modelo que
o mercado procura primeiro e é multilíngue por projeto; ele também é um
repositório fechado, então exige licença e token. `INJECTION_MODEL` troca para
ele numa configuração só.

### Injeção indireta é o risco que pertence ao RAG

Um trecho recuperado é colado no contexto e o modelo o lê do jeito que lê o
system prompt. Um recuperador trabalha em espaço de embedding e não tem noção
de "isto é dado" em vez de "isto é instrução", então um documento com uma
instrução escondida ataca **toda pergunta que o recupera**.

O corpus é portanto varrido **na ingestão**, uma vez por trecho, nunca por
pergunta: os documentos só mudam quando alguém indexa, então a resposta não
pode mudar entre duas perguntas. Medido em cinco trechos com um envenenado: um
sinalizado, quatro artigos genuínos limpos.

Um trecho sinalizado avisa em vez de recusar. Este corpus é regulação, e
regulação diz ao leitor o que fazer, então um classificador treinado em
jailbreak às vezes lê um artigo genuíno como instrução. Recusar indexar
apagaria a lei em silêncio.

### O que não está coberto

- **Recuperação com permissão.** Quem consegue perguntar consegue recuperar
  qualquer trecho. É o maior buraco que sobrou, e é o primeiro sobre o qual uma
  instituição regulada pergunta.
- **Dado pessoal na saída.** Só a pergunta é varrida, nunca a resposta.
- **Avaliação adversarial.** O classificador de injeção foi medido sobre oito
  casos escritos à mão, não contra uma suíte de red team.

---
## API HTTP

O mesmo agente atrás de uma interface HTTP. Os endpoints chamam
`agent.service`, a mesma orquestração que o CLI chama, então esta camada
traduz requisições e resultados e não guarda lógica própria.

```bash
rag serve                          # http://127.0.0.1:8080
rag serve --host 0.0.0.0 --port 80
rag serve --reload                 # desenvolvimento
```

Documentação interativa, gerada a partir dos schemas, em `/docs`.

| Método | Caminho | Para que serve |
|---|---|---|
| `POST` | `/ask` | Uma pergunta, sem memória |
| `POST` | `/chat` | Uma pergunta dentro de uma conversa |
| `DELETE` | `/chat/{session_id}` | Esquecer uma conversa |
| `POST` | `/feedback` | Registrar o que alguém achou de uma resposta |
| `GET` | `/health` | Vivacidade. Não checa mais nada |
| `GET` | `/ready` | Prontidão. Banco alcançável, índice populado |
| `GET` | `/status` | A configuração ativa |

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

Toda resposta carrega o que ela custou, os mesmos números que o CLI imprime.
Acrescente `"trace": true` ao corpo para receber o rastro de raciocínio junto.

### Conversas

`POST /chat` sem `session_id` abre uma e devolve o id dela. Mande esse id de
volta para continuar:

```bash
curl -X POST localhost:8080/chat -H "Content-Type: application/json"   -d '{"question": "o que caracteriza uma informação relevante?"}'
# -> {"session_id": "97c93e1d...", ...}

curl -X POST localhost:8080/chat -H "Content-Type: application/json"   -d '{"question": "e quem deve divulgar?", "session_id": "97c93e1d..."}'
```

**Onde as conversas moram** depende de `SESSION_BACKEND`.

`memory` é o padrão e não exige nada rodando. As conversas pertencem ao
processo que as atendeu, e o armazenamento tem teto de 100 e descarta a mais
antiga, porque cada uma guarda o histórico inteiro de mensagens e um dicionário
sem limite é vazamento de memória com nome simpático.

`redis` é o que torna o serviço escalável horizontalmente. Uma conversa aberta
contra uma réplica é legível pela seguinte, ela sobrevive a um restart, e o
Redis a expira depois de `SESSION_TTL_SECONDS` para que uma abandonada não
ocupe memória para sempre. `docker compose up` roda nesse modo.

Só as mensagens são guardadas, em JSON. O grafo do agente carrega closures que
não podem ser serializadas, e não precisa: ele é remontado a partir da
configuração a cada requisição. Uma conversa escrita por uma versão do sistema
continua legível pela seguinte.

### Autenticação

A API fica aberta sem `API_KEY` configurada, o que mantém o `rag serve`
funcionando num laptop. Defina uma e todo endpoint passa a exigi-la:

```bash
export API_KEY=$(openssl rand -hex 32)
curl -H "X-API-Key: $API_KEY" localhost:8080/health
```

Chave ausente ou errada devolve `401` nomeando o cabeçalho a enviar. A
comparação usa `hmac.compare_digest` e não `==`, porque uma comparação comum
retorna assim que dois caracteres diferem, e essa diferença de tempo basta para
adivinhar a chave um caractere por vez.

Deliberadamente não é um sistema de identidade. Não há usuários, escopos nem
rotação: qualquer coisa além de um segredo compartilhado pertence a quem emite
os tokens, na frente deste serviço.

### Falhas do provedor

Um modelo com taxa limitada ou brevemente indisponível é condição normal, não
algo para devolver ao chamador. `MAX_RETRIES` tenta de novo com recuo e
`REQUEST_TIMEOUT_SECONDS` limita uma chamada, ambos aplicados ao modelo de chat
e aos embeddings.

### Modos de falha

| Situação | Resposta |
|---|---|
| Índice vazio | `503` nomeando o passo de ingestão |
| Postgres inalcançável | `/ready` responde `503`; `/health` fica em `200` |
| Passou do limite de taxa | `429` com `Retry-After` |
| Corpo malformado | `422` vindo do schema |
| Chave de API ausente ou errada | `401`, quando `API_KEY` está definida |
| Sessão desconhecida no delete | `404` |

Um `session_id` desconhecido no `POST /chat` abre uma conversa nova em vez de
falhar: um cliente com um id de antes de um restart deve continuar funcionando.

### LangSmith

O LangChain se instrumenta sozinho, então o LangSmith não exige código nenhum
aqui:

```bash
export LANGSMITH_TRACING=true
export LANGSMITH_API_KEY=lsv2_...
```

O Langfuse é o padrão por ser aberto, auto-hospedável e independente do
framework, enquanto o LangSmith é mais fácil de ligar e mais amarrado ao
LangChain. Use um ou outro: mandar a mesma execução para duas plataformas
significa dois lugares para olhar o mesmo dado.

---
## Colocando para funcionar

Tudo que decide se as respostas continuam acontecendo, em vez de o que uma
resposta diz.

### Sondas, limites e workers

| Endpoint | Responde | Checa |
|---|---|---|
| `GET /health` | vivacidade | mais nada |
| `GET /ready` | prontidão | banco alcançável, índice populado |

**Eram um endpoint só, e ele checava o banco.** Isso é prontidão com nome de
vivacidade: um orquestrador reinicia o processo cuja sonda de vivacidade falha,
então o banco piscando reiniciaria todas as réplicas de uma vez, e é assim que
um problema de banco vira uma indisponibilidade. Uma sonda de prontidão que
falha tira a instância de rotação e a deixa viva, que é a resposta certa para
uma dependência brevemente ausente.

O healthcheck do contêiner aponta para `/ready`, porque o `service_healthy` do
Compose quer dizer "pronto para receber tráfego".

**O limite de taxa** é uma janela móvel por chamador: `60/minute` por padrão,
vazio para desligar. Um chamador é a chave de API quando existe, e o endereço
quando não, e a chave é resumida antes de virar chave de armazenamento. Toda
resposta carrega `X-RateLimit-Remaining`, então o cliente desacelera antes de
ser recusado em vez de depois. As sondas nunca são limitadas: um balanceador
consultando prontidão a cada dois segundos esgotaria sozinho um orçamento por
minuto.

> **Não é o slowapi.** Ele é a resposta usual para FastAPI e não funciona aqui.
> Os dois middlewares dele localizam a rota varrendo `app.routes` atrás de algo
> com `.endpoint`, e o FastAPI atual embrulha tudo que vem de `include_router`
> num `_IncludedRouter` que não tem. Toda requisição parece uma rota que ele
> não consegue identificar, e ele trata isso como isenta. A falha é silenciosa:
> o limitador se declara ativo e o teto nunca dispara. Usada a `limits`, a
> biblioteca sobre a qual o slowapi é construído.

**Onde os contadores moram** decide se o teto é um teto só.
`RATE_LIMIT_STORAGE` é vazio por padrão, o que os mantém no processo, e isso
está errado no instante em que existe mais de um: quatro workers contando cada
um as suas requisições aplicam sessenta por minuto quatro vezes. Medido, três
por minuto entre dois processos:

| Armazenamento | Seis requisições |
|---|---|
| no processo | `ok ok ok ok ok ok` |
| `redis://redis:6379/1` | `ok ok ok 429 429 429` |

Um armazenamento inalcançável cai para o processo e diz isso no log. Precisão é
a coisa certa a perder ali; recusar subir não é teto nenhum nem serviço nenhum.

**Workers**: `rag serve --workers 4`, ou `API_WORKERS`. Um processo serializa
as requisições, então uma pergunta de oito segundos bloqueia toda outra
pergunta por esses oito segundos. `--reload` precisa de um processo só e vence
`--workers`, o que o comando diz em vez de ignorar um deles em silêncio.

### Migrações de esquema

O Alembic é dono das extensões e da configuração de busca textual
`portuguese_unaccent`. As tabelas pertencem ao langchain-postgres, que as cria
na primeira escrita, e os dois índices de busca são construídos depois disso
porque não podem existir antes da tabela.

```bash
alembic upgrade head       # prepara um banco
alembic revision -m "..."  # começa uma mudança
alembic downgrade -1       # desfaz a última
```

A URL não está no `alembic.ini`. O `migrations/env.py` lê `DATABASE_URL` pelo
mesmo objeto de configuração que a aplicação usa, então existe um lugar só que
sabe onde o banco está e nenhuma credencial em arquivo versionado.

**A aplicação não aplica migrações.** Ela aplicava, e isso é anti-pattern acima
de uma réplica: vários processos subindo juntos correm para criar os mesmos
objetos, e uma migração longa trava todo boot em vez de um passo de
implantação. O que a aplicação faz agora é verificar, e falhar nomeando o
comando:

```
O banco em postgresql+psycopg://rag:***@localhost:5432/rag não tem as
migrações aplicadas. Rode: alembic upgrade head
```

No Compose um serviço `migrate` de uma tacada roda primeiro e a API espera por
`service_completed_successfully`.

---
## Rodando com Docker

Quatro serviços: o agente, Postgres com pgvector, Redis para sessões, e um
`migrate` de uma tacada que prepara o esquema e sai. O índice mora no
contêiner dele, com volume próprio, e sobrevive à aplicação inteira.

```bash
export OPENAI_API_KEY=sk-...        # Windows: $env:OPENAI_API_KEY='sk-...'

docker compose up -d                     # Postgres, Redis, migrate, e então a API
docker compose run --rm api ingest       # constrói o índice
curl localhost:8080/health
```

`docker compose up` sobe os quatro, em ordem. A API espera o Postgres aceitar
conexões **e** o `migrate` terminar com sucesso, então ela nunca sobe contra um
esquema que não está lá. O healthcheck dela aponta para `/ready`, porque o
`service_healthy` do Compose quer dizer "pronto para receber tráfego" e não "o
processo está vivo".

A imagem serve a API por padrão e continua rodando o CLI sob demanda, porque o
entrypoint é o próprio comando `rag`:

```bash
docker compose run --rm api ask "qual o prazo de suspensão de uma oferta?"
docker compose run --rm api eval
docker compose run --rm api ingest --reset
```

O índice sobrevive a reinicializações:

```bash
docker compose restart postgres
docker compose run --rm api status   # continua com 590 pedaços
```

`./data` é montado como somente leitura, então trocar o corpus não exige
rebuild. Para derrubar tudo, incluindo o índice:

```bash
docker compose down -v
```

**Sobre o tamanho da imagem:** a imagem de runtime tem ~1,9 GB, e quase tudo
isso é torch, que chega junto com os guardrails. Ela teria ~5,9 GB sem uma
linha no Dockerfile: a roda que o PyPI serve no Linux embute o runtime CUDA,
uns três gigabytes de bibliotecas nvidia para um contêiner sem GPU. Instalar o
torch do índice de CPU do PyTorch antes é o que evita isso.

Para comparação, ela tinha 422 MB antes dos guardrails, e 618 MB antes disso,
quando o armazenamento era o Chroma. Descartar o Chroma não foi otimização e
sim consequência: o `chromadb` arrastava `kubernetes`, `onnxruntime` e bindings
Rust, tudo isso maquinário para rodar o Chroma como servidor, coisa que este
contêiner nunca fez. Um cliente de Postgres é um driver.

---
## Avaliação

Testes de unidade provam que o código faz o que foi escrito para fazer. Eles
não dizem nada sobre o agente responder certo. Essa é outra pergunta, e é a
única que diz se uma mudança no prompt, no chunking ou no modelo melhorou ou
piorou as coisas.

```bash
rag eval                     # a suíte inteira, ~2 minutos, ~US$ 0,02
rag eval --limit 5           # uma amostra rápida
rag eval --min-score 0.90    # reprova abaixo de 90% em vez de abaixo do perfeito
rag eval --max-cost 0.05     # reprova se a execução custar mais que o esperado
rag eval --judge             # acrescenta um modelo que lê a frase
rag eval --compare <relatório>  # compara com uma execução anterior
rag eval --dataset meu.json  # as suas próprias perguntas
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

`recusa` aparece como `n/a` aqui porque nenhum dos cinco primeiros casos é de
fora do corpus: zero de zero aplicáveis não é a mesma coisa que reprovar.

A suíte inteira, todos os 29 casos, marca hoje **100%**. Cinco das seis
métricas são determinísticas, então esse número é reproduzível; `faithfulness`
é julgada por modelo e oscila, então uma execução em 100% não é promessa da
próxima.

As falhas são impressas com a resposta, os documentos recuperados e qual
métrica quebrou, e o comando sai com código diferente de zero quando a nota
geral cai abaixo de `--min-score`, então ele consegue barrar um release.

Cada execução grava um relatório com data e hora em `evals/results/`, e eles
ficam no repositório. Cada um registra o modelo, o modelo de embedding e o
`retrieval_k` ao lado da nota, porque um número sem a configuração por trás não
se compara com a próxima execução. O histórico mostra o efeito de uma mudança:
os relatórios aqui traçam 82%, 86%, 93%, 97% e 100%, cada passo uma
configuração só.

### Fundamentação

As métricas com referência comparam a resposta contra o dataset. Esta compara
contra **o que o agente de fato leu**.

Todo número que a resposta declara precisa aparecer num trecho recuperado, num
resultado de ferramenta, ou na pergunta. Um número que não está em nenhum
desses veio da memória do próprio modelo, e não depender dessa memória é a
razão inteira de existir recuperação.

Uma resposta pode estar correta, citar o arquivo certo, e ainda assim ser
infundada. Essa combinação se sustenta só enquanto a memória do modelo concorda
com o documento, e ela quebra em silêncio em regra interna, em versão nova de
uma norma, em qualquer coisa que os dados de treino ainda não contenham. Nada
mais na suíte detecta isso.

Números são a afirmação que vale checar numa regulação: eles carregam os
prazos, os percentuais e os limites, e são o que um modelo inventa com mais
confiança. O casamento normaliza os números, então "75 milhões" numa resposta e
"75000000" num resultado de calculadora são reconhecidos como um número só, e
uma resposta sem números não é avaliada em vez de ser zerada.

**Os limites dela, ditos com clareza:** ela checa números, não prosa. Um
qualificador inventado, um nome errado, uma condição invertida, tudo isso
passa. E um alarme falso numa resposta correta deixaria a métrica inútil, então
o casamento é deliberadamente tolerante.

Uma primeira ideia não sobreviveu: sinalizar uma chamada de ferramenta cujos
argumentos carregam um número que ninguém tinha lido ainda, o que pegaria o
agente escolhendo um multiplicador antes de o trecho voltar. Medida contra o
comportamento correto, ela disparava com a mesma frequência, porque um número
legitimamente muda de forma entre o documento e a expressão ("500 milhões" vira
`500000000`, "15%" vira `0.15`). Uma métrica que não distingue certo de errado
foi descartada em vez de entregue.

### Comparando duas execuções

Um diretório de relatórios registra o que aconteceu. Ele não diz o que mudou, e
ler dois arquivos JSON lado a lado para descobrir é como um histórico deixa de
ser usado.

```
$ rag eval --compare evals/results/20260830-212255.json

comparação com 20260830-212255.json
  retrieval_k          8 → 4
  overall              97% → 83%
  factual_accuracy     96% → 83%
  quebrado prazo-exigencias-primeiras
  1 regressão(ões)
```

As regressões vêm primeiro, porque um caso que começou a falhar é o que vale
ler. Acima delas fica a configuração que se moveu, que costuma ser a resposta
do porquê.

Cada relatório registra as configurações por trás dele: o modelo, o modelo de
embedding, a temperatura, as duas configurações de chunking, `retrieval_k`, o
domínio de conhecimento, e um hash do prompt renderizado. O hash do prompt
importa tanto quanto o resto: mudar a redação muda a nota, e sem uma impressão
digital essa mudança não deixa rastro.

Relatórios escritos antes disso carregam poucos campos, e a comparação diz isso
em vez de fingir que nada se moveu.

### Teto de custo

```bash
rag eval --max-cost 0.05
```

Sai com código diferente de zero quando a execução custa mais que o esperado.
Um prompt que ficou prolixo, ou um `retrieval_k` subido demais, aparece aqui
como número em vez de como surpresa na fatura.

### Avaliação no CI

A suíte roda pela aba Actions, e uma vez por semana sozinha:

```
Actions → Evaluation → Run workflow → min_score, max_cost, limit
```

A execução semanal existe porque o corpus para de mudar mas o modelo não. Um
provedor atualizando o `gpt-4o-mini` por baixo de um projeto congelado move a
nota sem nenhum commit a culpar, e uma execução toda segunda é como isso
aparece. Cada execução agendada commita o relatório dela, então a tendência
sobrevive à retenção de 30 dias dos artefatos.

Cada execução alcança o modelo real, então custa dinheiro e leva minutos. Essa
é a troca errada para uma checagem por push, e as checagens rápidas no `ci.yml`
já cobrem todo push. O relatório é enviado como artefato, inclusive quando a
execução fica abaixo do limiar, já que é justamente o detalhe dela que alguém
precisa ler.

Ela precisa da `OPENAI_API_KEY` em **Settings → Secrets and variables →
Actions**. Sem ela o job pula com uma mensagem em vez de falhar, porque um pull
request vindo de um fork nunca recebe segredos.

### Relação com as ferramentas existentes

Os nomes de métrica usados aqui são locais. Os conceitos não: cada um tem um
nome estabelecido na literatura de avaliação de RAG.

| Neste projeto | Nome padrão | Onde aparece |
|---|---|---|
| `retrieval` | context recall | RAGAS |
| `correctness` | answer correctness | RAGAS, DeepEval |
| `groundedness` | faithfulness, calculada | RAGAS, TruLens |
| `faithfulness` | LLM-as-a-judge faithfulness | RAGAS, LangSmith, DeepEval |
| `citation` | attribution | LangSmith |
| `refusal` | taxa de alucinação em perguntas sem resposta | RAGAS |

RAGAS, LangSmith Evaluation, DeepEval e Langfuse Datasets cobrem esse terreno,
e nenhum deles é usado aqui. Todos compartilham um padrão: um modelo de
linguagem avalia as respostas. Isso custa dinheiro em toda execução e oscila: a
mesma resposta pode tirar notas diferentes duas vezes, e uma suíte cujos
números se movem sozinhos não distingue regressão de ruído.

A troca feita no lugar: avaliação determinística contra um dataset menor,
verificado à mão. Vinte e nove casos cujas respostas foram lidas nos documentos
de origem, avaliados por operações de string e conjunto. O custo é cobertura,
já que essas métricas checam números e nomes de arquivo em vez de significado.
O ganho é que a mesma execução sempre produz o mesmo número, e avaliar não
custa nada.

Um modelo juiz é a escolha certa para avaliar prosa, onde a redação varia
legitimamente e um casamento de string não distingue uma frase fiel de uma
distorcida. É exatamente isso que `--judge` acrescenta, mantido separado e
opcional para que as notas reproduzíveis continuem reproduzíveis.

### As seis métricas

| Métrica | Precisa da resposta esperada? | O que checa |
|---|---|---|
| `retrieval` | sim | O documento certo voltou da busca |
| `citation` | sim | A resposta nomeia a fonte certa |
| `correctness` | sim | O número ou termo esperado está presente |
| `refusal` | sim | Fora do corpus, admitiu não saber |
| `groundedness` | não | Todo número declarado aparece no que ele leu |
| `faithfulness` | não | A frase bate com o trecho, avaliado por modelo |

A divisão na coluna do meio é a que importa, e é por isso que as métricas vivem
em código e não como avaliadores na plataforma.

As quatro primeiras comparam uma resposta contra uma **resposta certa
conhecida**. Elas só existem onde há um dataset. A pergunta de um usuário real
não tem saída esperada, então nada consegue avaliá-la desse jeito.

As duas últimas comparam a resposta contra **o que o agente recuperou**. Elas
não precisam de resposta esperada, e é por isso que funcionariam também sobre
tráfego de produção. A literatura chama isso de sem referência, e é sobre isso
que o RAGAS construiu a reputação dele.

`faithfulness` não é uma camada em cima das outras. É a sexta métrica, e a
única calculada por um modelo em vez de por comparação de string. Ela existe
porque as outras cinco aprovam uma resposta que declara o número certo
invertendo a condição em volta dele: a regulação diz que um fato **pode** ser
omitido, a resposta diz que ele **deve** ser, e nenhum número se moveu.

### Na plataforma

A suíte local escreve um relatório por execução em `evals/results/`. Isso
funciona até o diretório crescer além do que alguém abre, e a única comparação
que ele oferece é um comando lendo dois arquivos.

Empurrar o dataset para o Langfuse transforma cada execução num experimento
rastreado:

```bash
rag dataset push          # manda as perguntas para o Langfuse
rag eval                  # roda elas lá
```

Cada caso ganha um trace próprio, as seis métricas penduram nele como notas, e
duas execuções ficam lado a lado numa interface feita para essa comparação. A
execução carrega a configuração como metadado, então uma nota nunca se separa
das configurações que a produziram.

O arquivo do dataset fica no git. Um dataset versionado junto do código é o que
torna uma nota reproduzível, e é o padrão: as perguntas mudam com o sistema, e
um pull request que acrescenta um caso deve mostrar esse caso no diff. O que
vai para a plataforma são os resultados.

O id do caso vira o id do item, então `dataset push` atualiza itens no lugar em
vez de duplicá-los, do mesmo jeito que a ingestão é idempotente.

As métricas são as mesmas funções que a suíte local usa, embrulhadas como
avaliadores do Langfuse. Reaproveitá-las é o que impede os dois caminhos de
discordarem, e elas continuam determinísticas e gratuitas dos dois jeitos.

Uma métrica que não se aplica não registra nada em vez de registrar zero. Zero
seria lido como falha, e o schema recusa nulo: uma pergunta fora do corpus não
tem recuperação a avaliar, e dizer isso é diferente de reprová-la.

### Revisão humana

Com o dataset na plataforma, a fila de anotação funciona sem código nenhum.
Mande traces para uma fila na interface do Langfuse, revise as respostas à mão,
e os rótulos voltam como notas ao lado das automáticas. É a única coisa aqui
que nenhuma métrica determinística consegue fazer: julgar se uma resposta lê
bem e significa o que o documento significa.

### O dataset

`evals/dataset.json` guarda 29 perguntas: 25 respondíveis e **4
deliberadamente fora do corpus**. Os casos fora do corpus são os importantes.
Eles medem se o agente admite ignorância em vez de inventar, o que nada mais no
projeto consegue pegar.

Todo fato foi extraído dos PDFs indexados, não escrito de memória.

### Toda métrica é determinística

Cinco das seis são operações de string e conjunto: mesma resposta, mesma nota,
sem custo extra. Um modelo de linguagem usado como juiz oscila entre execuções,
e uma suíte cujos números se movem sozinhos não distingue regressão de ruído, e
é por isso que `faithfulness` é a sexta e fica separada.

A contrapartida é honesta: `retrieval` checa que o *documento* certo voltou,
não o *trecho* certo. Numa regulação de 143 páginas cheia de prazos quase
idênticos, isso é um instrumento grosseiro, e as falhas abaixo expuseram
exatamente isso.

### O que ela encontrou

Rodar pela primeira vez já se pagou:

| Achado | Correção | Resultado |
|---|---|---|
| Documento certo, prazo errado: 5 casos em que a resposta citava o arquivo correto com o número errado | `RETRIEVAL_K` de 4 para 8 | 82% → 86% |
| O agente nunca parava de buscar uma resposta que não existia, até a janela de contexto estourar e matar a execução inteira | Uma regra limitando as tentativas, mais `recursion_limit` no grafo | 86% → 93% |
| Um caso que falhava abortava a suíte inteira | Isolamento de erro por caso no executor | Os outros 27 resultados sobrevivem |
| Uma pergunta tão ambígua que o agente era reprovado por uma resposta correta, já que o artigo carrega cinco prazos diferentes para "exigências" | Dividida em duas perguntas específicas | O dataset ficou honesto |
| Regras separadas das exceções que as qualificam, porque a quebra cortava a cada 1000 caracteres | `CHUNK_STRATEGY=articles` | 93% → 97% |
| Nada checava se os números de uma resposta vinham dos documentos ou da memória do modelo | Fundamentação | 100%, por ora uma trava de regressão e não um achado |
| Um caso falhou por semanas. O trecho que enuncia o prazo estava na posição 31 de 590 pelo embedding, então nenhum reordenador o alcançaria | Busca híbrida, fundida por RRF | 97% → 100% |
| O mesmo pedaço não conseguia existir em duas coleções: gravar na segunda tirava a linha da primeira, em silêncio | A coleção faz parte do id do pedaço | Achado por um teste de integração, não por um usuário |

O primeiro é o perigoso: um número errado com citação correta parece mais
confiável que um número errado sozinho.

Um caso que falha tem três causas possíveis, e só ler a resposta as distingue:
o agente escreveu mal, a recuperação trouxe o trecho errado, ou a pergunta em
si era ambígua. Confundir a terceira com a primeira significa "consertar" um
agente que estava certo.

---
## Observabilidade

Toda resposta já informa o próprio custo localmente. Isso diz o total; não diz
para onde foram o tempo e os tokens. Para isso, o agente consegue emitir um
trace completo para o [Langfuse](https://langfuse.com), com uma linha por
chamada de modelo, chamada de ferramenta e recuperação, cada uma carregando a
própria latência, tokens e preço.

```
rag.ask                                    3.78s   1634 tok   $0.00031
├─ ChatOpenAI                              1.71s    411 tok
│    └─ decidiu: search_documentation
├─ tool: search_documentation              0.54s
└─ ChatOpenAI                              1.52s   1223 tok
     └─ resposta final
```

Ligue definindo as duas chaves. Uma conta gratuita em
[cloud.langfuse.com](https://cloud.langfuse.com) basta:

```
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com     # ou https://us.cloud.langfuse.com
```

Deixe de fora e nada é enviado, nada é importado, e o agente se comporta
igual. Observabilidade nunca pode quebrar a coisa que ela observa, então uma
chave recusada ou um Langfuse inalcançável registra um aviso e se desliga em
vez de reprovar a resposta.

Cada conversa do `rag chat` ganha um id de sessão, então os turnos dela se
agrupam no painel em vez de aparecerem como execuções sem relação. Os traces
carregam o modelo, o modelo de embedding, o domínio de conhecimento e
`retrieval_k` como metadado, então um trace do mês passado ainda explica qual
configuração o produziu.

**Por que isso importa aqui:** o agente às vezes emite as chamadas de
ferramenta em paralelo, decidindo `calculate` antes de ter lido o trecho
recuperado. A resposta ainda pode sair certa enquanto o número veio da memória
do modelo e não do documento. No terminal isso passa fácil. Num trace, as duas
chamadas penduradas na mesma chamada de modelo tornam isso óbvio.

---
## Gestão de prompts

O prompt decide como o agente se comporta, e muda muito mais que o código em
volta dele. Guardado como string no fonte, toda mudança de redação custa um
commit, um build e um deploy, e nenhum registro sobrevive de qual texto
produziu qual nota.

Publicado no Langfuse, ele vira um ativo versionado:

```bash
rag prompt push -m "regra nova sobre citação"   # publica sob o label
rag prompt show                                 # o que está em vigor, e de onde
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

Editar o texto na interface do Langfuse e mover o label `production` é como uma
versão nova chega ao agente. Fazer rollback é mover o label para a anterior.
Nenhuma das duas coisas toca o repositório.

### O que é publicado, e o que não é

Quatro prompts vão para o Langfuse:

| Prompt | O que o modelo faz com ele |
|---|---|
| `rag-agent-system` | As regras sob as quais ele responde |
| `rag-agent-search-tool` | Decide se uma pergunta precisa de recuperação |
| `rag-agent-calculator-tool` | Decide se uma pergunta precisa de aritmética |
| `rag-agent-judge` | A rubrica contra a qual a métrica `faithfulness` avalia |

A linha divisória é para que serve o texto. Uma **descrição que o modelo lê
para decidir** é ajustada do jeito que um prompt é ajustado, então ela pertence
a onde prompts são versionados. As descrições de ferramenta são exatamente
isso: o modelo nunca vê o corpo de uma ferramenta, só o nome e a descrição, e
reescrever uma muda quando ela é chamada.

O que fica no código é o texto que uma ferramenta **devolve**: `"Divisão por
zero."`, `"Nenhum trecho relevante encontrado na documentação."`. Isso reporta
o que aconteceu durante uma execução. São fatos sobre execução e não
instruções, e ninguém faz teste A/B com eles.

`_NO_RESULTS` fica mais perto da linha, já que é o que leva o agente a dizer
que não achou nada. Ele fica no código porque enuncia um fato; a instrução de
admitir ignorância vive no system prompt, onde pode ser ajustada.

As duas ferramentas são portanto construídas por uma fábrica e não pelo
decorador `@tool`: um decorador congela a docstring no import, e uma descrição
buscada na hora da chamada é a ideia inteira.

### Ela nunca bloqueia uma resposta

Sem o Langfuse configurado, os templates em `prompts/templates.py` são usados e
tudo funciona. Com o Langfuse configurado mas inalcançável, os mesmos templates
são usados e um aviso é registrado. Um repositório de prompts que consegue
impedir o agente de responder é pior que nenhum repositório de prompts.

O SDK guarda em cache por `PROMPT_CACHE_SECONDS`, então uma requisição não paga
uma ida e volta para buscar texto que raramente muda.

### Uma sintaxe de marcador só

Os templates usam `{{domain}}`, a forma que o Langfuse compila, nos dois
caminhos. O texto local é portanto publicado literalmente, e a mesma string
renderiza tenha ela vindo da plataforma ou do arquivo.

### Registrado junto da nota

Todo relatório de avaliação carrega `prompt_source` e `prompt_version` ao lado
do modelo e do chunking. Uma execução avaliada contra a versão 3 não se compara
a uma avaliada contra a versão 4, e agora o relatório diz qual estava em vigor.

---
## Feedback

O dataset de avaliação é escrito por quem construiu o sistema, o que significa
que ele testa as perguntas que essa pessoa imaginou. Feedback de uso real é a
única fonte das que ela não imaginou.

Toda resposta carrega um `run_id`. Devolva junto com um veredito:

```bash
curl -X POST localhost:8080/feedback -H "Content-Type: application/json"   -d '{"run_id": "9b8c3a27...", "useful": false, "comment": "citou o artigo errado"}'
```

O veredito é registrado no Langfuse como uma nota no trace que produziu a
resposta, que é onde a plataforma já guarda o prompt, os trechos recuperados e
o custo daquela mesma execução. Mande o `trace_id` junto do `run_id` para
anexar.

Uma cópia local também é acrescentada a `logs/feedback.jsonl`, então o ciclo
ainda fecha com o rastreamento desligado:

```json
{"recorded_at": "2026-08-31T15:31:04+00:00", "run_id": "9b8c3a27...",
 "useful": false, "comment": "citou o artigo errado", "sent_to_langfuse": true}
```

**Para que serve.** As respostas rejeitadas são as candidatas a novos casos de
avaliação. Uma pergunta que o agente errou em uso real pertence ao
`dataset.json`, e dali em diante ela não consegue regredir sem que se note.
Esse ciclo é o que impede a suíte de testar só o que foi imaginado no primeiro
dia.

Nada valida que um `run_id` pertence a uma resposta real. Recusar ids
desconhecidos significaria manter toda resposta em memória, e uma entrada
perdida de vez em quando custa menos que isso.

---
## Estrutura do projeto

```
src/rag_agent/
├── config.py          configurações, lidas do ambiente e validadas no boot
├── types.py           AnswerResult, SearchHit, ToolCall, RunMetrics
├── providers.py       clientes de LLM e embedding, o único lugar com OpenAI
├── cli.py             só apresentação, nenhuma lógica de domínio
│
├── prompts/           as instruções, e de onde elas são lidas
│   ├── __init__.py        busca no Langfuse, renderiza, cai para o texto
│   └── templates.py       o texto em si, e mais nada
│
├── observability/     o que a execução fez, o que custou, e o registro disso
│   ├── tracing.py         Langfuse: traces, notas, registro de prompts
│   ├── pricing.py         preços de token, com data
│   └── logging_setup.py   console e arquivo
│
├── guardrails/        o que é recusado na entrada, registrado na saída
│   ├── checks.py          a decisão: o que bloqueia, o que só registra
│   ├── scanners.py        LLM Guard, estreitado e com CPF e CNPJ
│   └── injection.py       o classificador, nas perguntas e no corpus
│
├── indexing/          loader · splitter · database · vector_store · keyword · hybrid · reranker
├── tools/             um módulo por ferramenta, registrado em build_tools()
├── agent/             service (montagem + orquestração) · trace
├── api/               routes · schemas · sessions · security · limits · feedback
└── evaluation/        dataset · metrics · runner · comparison · configuration

migrations/            Alembic. A aplicação verifica o esquema, nunca o aplica
docs/diagrams/         o diagrama de arquitetura, como código-fonte
```

Quatro módulos soltos e oito pacotes. Os quatro são os que toda camada procura
e nenhuma delas possui: configurações, tipos de domínio, a fronteira do
provedor, e o terminal.

Um pacote existe onde alguma coisa cresce: `indexing/` a cada novo formato de
arquivo, `tools/` a cada nova ferramenta, `guardrails/` a cada nova classe de
coisa a recusar. O `cli.py` é a exceção e a dívida reconhecida: 742 linhas que
deveriam ser um pacote antes de mais um comando entrar.

| Para mudar... | Edite |
|---|---|
| A base de conhecimento | `data/`, e então `rag ingest` |
| Como o agente se comporta | Langfuse, ou `prompts/templates.py` como queda |
| Acrescentar uma ferramenta | `tools/` |
| Chunking ou recuperação | `.env` |
| O provedor do modelo | `providers.py` |
| Preços de token | `observability/pricing.py` |
| Acrescentar um endpoint | `api/routes.py` |
| O que é recusado | `guardrails/` |
| O esquema | `migrations/`, e então `alembic upgrade head` |

As interfaces ficam finas porque a orquestração vive em `agent/service.py`.
Acrescentar uma API HTTP ou um bot é embrulhar esse serviço, não reescrevê-lo.

---
## Desenvolvimento

Com o ambiente ativo:

```bash
pytest                          # suíte inteira
pytest -v                       # uma linha por teste
pytest -m "not integration"     # só os rápidos, sem rede, sem custo de API
pytest --cov=rag_agent          # com cobertura
pytest -k calculator            # filtra por nome

ruff check . && ruff format .   # lint e formatação
mypy                            # checagem de tipos
```

Todo push roda três jobs pelo GitHub Actions (`.github/workflows/ci.yml`): as
checagens de qualidade em Ubuntu e Windows, a suíte de integração contra um
Postgres real, e um build do Docker.

Os testes de unidade cobrem a lógica pura e não precisam de nada rodando. A
suíte de integração exercita o SQL contra um serviço `pgvector`, com um
embedding falso determinístico para não precisar de chave de API: SQL é a única
coisa que um dublê não verifica, e um `DELETE` com `WHERE` errado passa em toda
a suíte de unidade e esvazia o índice em produção. Ela roda em série, porque
esses testes compartilham um banco.

O `pytest` roda quatro workers por padrão. Não `auto`: cada worker carrega os
modelos de guardrail no próprio processo, e passando de quatro a pressão de
memória custa mais do que o paralelismo rende.

---
## Solução de problemas

| Sintoma | Correção |
|---|---|
| `rag` não reconhecido / command not found | O ambiente virtual não está ativo. Rode `.\.venv\Scripts\Activate.ps1`, ou chame `.\.venv\Scripts\rag.exe` direto. |
| `a execução de scripts foi desabilitada neste sistema` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, uma vez. |
| `pytest` não reconhecido | Mesma causa. Ative o ambiente primeiro. |
| `O índice está vazio` | Rode `rag ingest` |
| `Pasta de dados não encontrada` | Verifique `DATA_DIR` com `rag status` |
| Erro de autenticação da OpenAI | Verifique `OPENAI_API_KEY` no `.env` |
| Respostas sem sentido depois de trocar de modelo | Rode `rag ingest --reset` |
| Respostas sem detalhe | Aumente `RETRIEVAL_K` ou `CHUNK_SIZE` |
| Acentos quebrados no Windows | `set PYTHONIOENCODING=utf-8` |
| `pip install -e .` falha num cabeçalho do torch | Ligue o suporte a caminho longo no Windows: `Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled -Value 1` |
| Toda pergunta recusada como injeção | Verifique `INJECTION_MODEL`. O padrão do LLM Guard recusa português |
| `RerankerUnavailableError` | Reinstale as dependências, ou defina `RERANK_STRATEGY=none` |
| Postgres inalcançável | `docker compose up -d postgres`, ou verifique `DATABASE_URL` |

---
## Licença

MIT.
