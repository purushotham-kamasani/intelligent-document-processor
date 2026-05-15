"""LLM client factory."""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.base import LLMClient
from app.llm.mock import MockLLMClient

_logger = get_logger(__name__)


def build_llm_client() -> LLMClient:
    settings = get_settings()
    if settings.llm_provider == "mock":
        _logger.info("llm.init", provider="mock", model=settings.llm_model)
        return MockLLMClient(model=settings.llm_model)
    # Stubs for real providers — implement and uncomment as needed.
    # if settings.llm_provider == "openai":
    #     from app.llm.openai_client import OpenAIClient
    #     return OpenAIClient(model=settings.llm_model)
    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider!r}")
