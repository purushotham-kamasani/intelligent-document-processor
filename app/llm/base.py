"""LLM client interface — provider-agnostic."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    metadata: dict[str, Any]


class LLMClient(ABC):
    """Async interface every concrete LLM provider implements."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: str = "text",
    ) -> LLMResponse:
        raise NotImplementedError

    @property
    @abstractmethod
    def model_name(self) -> str:
        raise NotImplementedError
