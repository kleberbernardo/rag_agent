"""Configuração central da aplicação, lida do ambiente e validada no boot."""

# lru_cache = "guarde o resultado desta função e reuse nas próximas chamadas"
from functools import lru_cache

# Path = caminho de arquivo como objeto (funciona igual no Windows, Linux e Mac)
from pathlib import Path

# Field = descreve UM campo (valor padrão, limites). SecretStr = string que se esconde ao ser impressa
from pydantic import Field, SecretStr

# BaseSettings = classe que lê variáveis de ambiente. SettingsConfigDict = ajustes dessa leitura
from pydantic_settings import BaseSettings, SettingsConfigDict

# __file__ é o caminho DESTE arquivo | .resolve() transforma em caminho absoluto
# .parents[2] sobe 3 níveis: config.py -> rag_agent/ -> src/ -> raiz do projeto
PROJECT_ROOT = Path(__file__).resolve().parents[2]


# Herdar de BaseSettings faz cada campo abaixo ser lido de uma variável de ambiente
class Settings(BaseSettings):
    """Todos os ajustes da aplicação em um só lugar.

    Cada campo é lido da variável de ambiente de mesmo nome em maiúsculas
    (chat_model <- CHAT_MODEL) ou do arquivo .env. Configuração inválida
    derruba a aplicação no boot, com mensagem clara.
    """

    # env_file: também procure num arquivo chamado .env | extra="ignore": variável desconhecida no .env não quebra nada
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Credencial ---
    # SecretStr esconde o valor em logs e prints. Vazio por padrão: quem não configurar recebe erro claro da OpenAI
    openai_api_key: SecretStr = Field(default=SecretStr(""))

    # --- Modelos ---
    # Qual modelo conversa. gpt-4o-mini: barato e suficiente pra RAG
    chat_model: str = Field(default="gpt-4o-mini")
    # Qual modelo converte texto em vetores. Tem que ser O MESMO na ingestão e na busca, senão os vetores não se comparam
    embedding_model: str = Field(default="text-embedding-3-small")
    # 0 = determinístico (mesma pergunta, mesma resposta). ge/le = limites mínimo e máximo aceitos
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    # --- Chunking (usado no módulo 2) ---
    # Tamanho máximo de cada pedaço de documento, em caracteres. gt=0 significa "tem que ser maior que zero"
    chunk_size: int = Field(default=1000, gt=0)
    # Quantos caracteres se repetem entre um pedaço e o seguinte, pra não cortar uma ideia ao meio
    chunk_overlap: int = Field(default=200, ge=0)

    # --- Busca (usada no módulo 3) ---
    # Quantos trechos a busca traz por pergunta. 4 é o equilíbrio: contexto suficiente sem inflar o custo
    retrieval_k: int = Field(default=4, gt=0)

    # --- Caminhos ---
    # Pasta onde ficam seus documentos. O "/" junta caminhos (é sobrecarga do operador no Path)
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    # Pasta onde o banco vetorial grava em disco. Começa com ponto = oculta, e entra no .gitignore
    vector_store_dir: Path = Field(default=PROJECT_ROOT / ".chroma")
    # Nome da "tabela" dentro do banco vetorial. Permite ter vários conjuntos de documentos no mesmo banco
    collection_name: str = Field(default="rag_agent_docs")


# @lru_cache faz a função rodar UMA vez; as próximas chamadas devolvem o resultado guardado
@lru_cache
def get_settings() -> Settings:
    """Devolve a configuração como singleton (lida do disco uma vez só)."""
    # Settings() sem argumentos = leia tudo do ambiente e do .env, e valide
    return Settings()
