"""Central application settings, read from the environment and validated at boot."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_MARKER = "pyproject.toml"


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

    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    vector_store_dir: Path = Field(default=PROJECT_ROOT / ".chroma")
    collection_name: str = Field(default="rag_agent_docs")

    log_dir: Path = Field(default=PROJECT_ROOT / "logs")


@lru_cache
def get_settings() -> Settings:
    """Return the settings singleton, read from disk only once."""
    return Settings()
