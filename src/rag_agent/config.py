"""Central application settings, read from the environment and validated at boot."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_MARKER = "pyproject.toml"


class VectorStoreMode(StrEnum):
    """Where the vector store lives."""

    EMBEDDED = "embedded"
    SERVER = "server"


def _find_project_root() -> Path:
    """Walk up from this file until the directory holding the project marker."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / _ROOT_MARKER).is_file():
            return candidate
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _find_project_root()


class Settings(BaseSettings):
    """Every tunable value of the application, in one validated place.

    Each field is read from the uppercase environment variable of the same
    name (chat_model <- CHAT_MODEL) or from the .env file. Invalid values
    stop the application at boot with a clear message.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: SecretStr = Field(default=SecretStr(""))

    chat_model: str = Field(default="gpt-4o-mini")
    embedding_model: str = Field(default="text-embedding-3-small")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    chunk_size: int = Field(default=1000, gt=0)
    chunk_overlap: int = Field(default=200, ge=0)

    retrieval_k: int = Field(default=4, gt=0)

    knowledge_domain: str = Field(default="a documentação interna da organização", min_length=3)
    """What the knowledge base is about, in the language of the answers.

    This is injected into the system prompt and into the search tool's
    description, which is what keeps the agent domain-agnostic: pointing it
    at a different corpus is a configuration change, not a code change.
    """

    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    log_dir: Path = Field(default=PROJECT_ROOT / "logs")

    vector_store_mode: VectorStoreMode = Field(default=VectorStoreMode.EMBEDDED)
    vector_store_dir: Path = Field(default=PROJECT_ROOT / ".chroma")
    chroma_host: str = Field(default="localhost")
    chroma_port: int = Field(default=8000, gt=0, le=65535)
    collection_name: str = Field(default="rag_agent_docs")

    langfuse_public_key: SecretStr = Field(default=SecretStr(""))
    langfuse_secret_key: SecretStr = Field(default=SecretStr(""))
    langfuse_host: str = Field(default="https://cloud.langfuse.com")

    @property
    def tracing_enabled(self) -> bool:
        """Tracing turns itself on only when both Langfuse keys are present."""
        return bool(
            self.langfuse_public_key.get_secret_value()
            and self.langfuse_secret_key.get_secret_value()
        )


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton, read from disk only once."""
    return Settings()
