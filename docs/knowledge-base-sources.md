# Knowledge base sources

The documents in this folder are official acts issued by the **Comissão de
Valores Mobiliários (CVM)**, the Brazilian securities and exchange commission.
They were downloaded unmodified from the CVM's public legislation portal.

Under Brazilian copyright law (Lei 9.610/1998, art. 8, IV), the texts of laws,
decrees, regulations and other official acts are not subject to copyright
protection, so redistributing them here is lawful.

| File | Document | Subject | Source |
|---|---|---|---|
| `cvm-resolucao-35-adequacao-de-produtos.pdf` | Resolução CVM nº 35 (consolidated) | Suitability — the duty to verify that a product, service or transaction fits the client's profile | [conteudo.cvm.gov.br](https://conteudo.cvm.gov.br/legislacao/resolucoes/resol035.html) |
| `cvm-resolucao-44-informacoes-relevantes.pdf` | Resolução CVM nº 44 (consolidated) | Disclosure of material information and restrictions on trading with privileged information | [conteudo.cvm.gov.br](https://conteudo.cvm.gov.br/legislacao/resolucoes/resol044.html) |
| `cvm-resolucao-160-ofertas-publicas.pdf` | Resolução CVM nº 160 (consolidated) | Public offerings for the distribution of securities | [conteudo.cvm.gov.br](https://conteudo.cvm.gov.br/legislacao/resolucoes/resol160.html) |

Retrieved on 30 August 2026, from the consolidated versions published by the
CVM. Consolidated texts incorporate later amendments, but they are a
convenience publication — for any legal purpose, consult the current version
on the CVM portal.

## Replacing this corpus

Nothing in the code depends on these documents. To point the agent at your own:

1. Empty `data/` and drop your files in (`.md`, `.txt`, `.markdown`, `.rst`,
   `.pdf`).
2. Set `KNOWLEDGE_DOMAIN` in `.env` to describe the new subject, in the
   language you want the answers in.
3. Run `rag ingest --reset`.
