"""Application configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Loaded from env / .env and validated at startup."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "intelligent-document-processor"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/v1"

    # --- Database ---
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/docs"

    # --- LLM ---
    llm_provider: Literal["mock", "openai", "anthropic"] = "mock"
    llm_model: str = "mock-gpt-4o-mini"
    llm_timeout_seconds: int = 30
    llm_max_retries: int = Field(default=3, ge=0, le=10)

    # --- Storage ---
    storage_path: Path = Path("./storage/uploads")
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)

    # --- Batch processing ---
    batch_max_concurrency: int = Field(default=4, ge=1, le=50)
    batch_document_timeout_seconds: int = Field(default=120, ge=1)

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def is_test(self) -> bool:
        return self.app_env == "test"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    # Ensure storage path exists at startup so we fail fast on permissions.
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    return settings
